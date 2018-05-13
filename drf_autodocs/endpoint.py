from rest_framework.serializers import BaseSerializer, ChoiceField, RelatedField, ManyRelatedField
from rest_framework.filters import SearchFilter
from inspect import getdoc
from django.contrib.admindocs.views import simplify_regex
from drf_autodocs import builtin_docs
from django.conf import settings
from django.utils.encoding import force_text, smart_text
from rest_framework.utils import formatting
import re

class Endpoint:
    counter = 0

    def __init__(self, pattern, prefix=None):
        self.id = Endpoint.counter
        self.header_regex = re.compile('^[a-zA-Z][0-9A-Za-z_]*:')
        self.extra_method = False
        Endpoint.counter += 1

        self.pattern = pattern
        self.view = pattern.callback
        self.methods = self._get_allowed_methods()
        self.complete_path = self._get_complete_path(pattern, prefix)

        self.name = self._get_endpoint_name()

        if hasattr(self.view.cls, 'extra_url_params'):
            self.extra_url_params = self.view.cls.extra_url_params

        if hasattr(self.view.cls, 'filter_backends') and len(getattr(self.view.cls, 'filter_backends')) > 0:
            self._collect_filter_backends()

        if hasattr(self.view.cls, 'authentication_classes') and self.view.cls.authentication_classes is not None:
            self.authentication_classes = [(cls.__name__, getdoc(cls)) for cls in self.view.cls.authentication_classes]

        if hasattr(self.view.cls, 'permission_classes') and self.view.cls.permission_classes is not None:
            self.permission_classes = [(cls.__name__, getdoc(cls)) for cls in self.view.cls.permission_classes]

        self.docstring = self._get_doc()

        if hasattr(self.view.cls, 'req_res_autodocs') :
            self._parse_req_res_doc()
        else :
            if hasattr(self.view.cls, 'serializer_class') and self.view.cls.serializer_class is not None:
                if not set(self.methods) == {'GET', 'OPTIONS'}:
                    self.input_fields = self._get_serializer_fields(self.view.cls.serializer_class())
                else:
                    self.output_fields = self._get_serializer_fields(self.view.cls.serializer_class())

            if hasattr(self.view.cls, 'response_serializer_class'):
                self.output_fields = self._get_serializer_fields(self.view.cls.response_serializer_class())

    def _parse_req_res_doc(self) :
        if self.extra_method :
            description = self.get_view_description(self.extra_method)
        else :
            description = self.get_view_description(self.view.cls, 'req_res_autodocs')

        sections = self._parse_docs_to_map(description, self.header_regex)
        if not set(self.methods) == {'GET', 'OPTIONS'}:
            self.input_fields_text = ''
            for method in self.methods:
                self.input_fields_text += method.upper() + '\n' + sections[method.lower() + '_req']
        else:
            self.output_fields_text = ''
            for method in self.methods:
                self.output_fields_text += method.upper() + '\n' + sections[method.lower() + '_req']
        

    def _parse_docs_to_map(self, doc, regex) :
        lines = [line for line in doc.splitlines()]
        current_section = ''
        sections = {'': ''}
        for line in lines:
            if self.header_regex.match(line):
                current_section, seperator, lead = line.partition(':')
                sections[current_section] = lead.strip()
            else:
                sections[current_section] += '\n' + line.replace('\t', '  ')
        return sections

    def get_view_description(self, obj, attr='__doc__', html=False):
        """
        Get the doc string from either cls or function, parse it and return
        """
        description = getattr(obj, "__doc__", "No description provided by developer")
        description = formatting.dedent(smart_text(description))
        if html:
            return formatting.markup_description(description)
        return description

    def _get_doc(self):

        # Check if the url pattern refers to dynamic routes
        # One Endpoin for one dynamic route. Need not be the case of others.
        # Check if it has actions - Viewset logic
        actions_map = getattr(self.view, 'actions', False)
        if actions_map and len(actions_map.keys()) == 1 :
            dynamic_method = list(actions_map.values())[0]
            for m in self.view.cls.get_extra_actions():
                if m.__name__ == dynamic_method:
                    self.extra_method = m
                    break;

        description =  self.get_view_description(self.extra_method) if self.extra_method else self.get_view_description(self.view.cls)

        sections = self._parse_docs_to_map(description, self.header_regex)

        if not actions_map :
            actions_map = {m.upper(): getattr(self.view.cls, m) for m in self.view.cls.http_method_names if hasattr(self.view.cls, m)}
        doc = ''
        # TODO: Check for View based route
        for method_name, method in actions_map.items() :
            if not type(method) is str :
                method = method_name
            if method in sections:
                doc += method_name.upper() + '\n' + sections[method].strip() + '\n\n' 

        return doc if doc else description

    def _get_endpoint_name(self):
        if hasattr(settings, 'AUTODOCS_ENDPOINT_NAMES') and settings.AUTODOCS_ENDPOINT_NAMES == 'view':
            ret = ''.join(
                [
                    (' %s' % c if c.isupper() and not self.view.__name__.startswith(c) else c)
                    for c in self.view.__name__
                    ]
            ).replace('-', ' ').replace('_', ' ').title()
            return ret
        else:
            return self.pattern.name.replace('-', ' ').replace('_', ' ').title()

    def _collect_filter_backends(self):
        self.filter_backends = []
        for f in self.view.cls.filter_backends:
            if f in builtin_docs.filter_backends:
                if f is SearchFilter:
                    if hasattr(self.view.cls, 'search_filters'):
                        doc = builtin_docs.filter_backends[f](self.view.cls.search_filters)
                    else:
                        doc = "Developer didn't specify any fields for search"
                else:
                    doc = builtin_docs.filter_backends[f]
                self.filter_backends.append((f.__name__, doc))
            else:
                self.filter_backends.append((f.__name__, getdoc(f)))

    def _get_allowed_methods(self):
        methods = []
        if hasattr(self.view, 'actions'):
            methods = [m.upper() for m in self.view.actions.keys()]
        elif hasattr(self.view.cls, 'allowed_methods'):
            # TODO: Check for View based route
            methods = [m.upper() for m in self.view.cls.http_method_names if hasattr(self.view.cls, m)]

        return methods

    @staticmethod
    def _get_complete_path(pattern, prefix=None):
        try:
            if hasattr(pattern, "_regex"):
                regex = pattern._regex
            elif hasattr(pattern.pattern, "_regex"): 
                regex = pattern.pattern._regex
            else :
                regex = str(pattern.pattern)
        except:
            regex = ""
        prefix = prefix.rstrip('/')
        regex = simplify_regex(regex).lstrip('/')
        complete_path = '%s/%s' % (prefix, regex)
        return complete_path

    def _get_serializer_fields(self, serializer):
        fields = []

        if hasattr(serializer, 'get_fields'):
            for key, field in serializer.get_fields().items():
                to_many_relation = True if hasattr(field, 'many') else False
                sub_fields = []

                if to_many_relation:
                    sub_fields = self._get_serializer_fields(field.child) if isinstance(field, BaseSerializer) else None
                else:
                    sub_fields = self._get_serializer_fields(field) if isinstance(field, BaseSerializer) else None
                field_data = {
                    "name": key,
                    "read_only": field.read_only,
                    "type": str(field.__class__.__name__),
                    "sub_fields": sub_fields,
                    "required": field.required,
                    "to_many_relation": to_many_relation,
                    "help_text": field.help_text,
                    "write_only": field.write_only
                }
                if isinstance(field, ChoiceField) and not isinstance(field, (RelatedField, ManyRelatedField)):
                    field_data['choices'] = field.choices

                if isinstance(field, RelatedField):
                    if hasattr(field, 'queryset') and hasattr(field.queryset, 'model'):
                        field_data['help_text'] = ('{}\nRequires/renders pk(id) of {} as integer'.format(
                            field.help_text if field.help_text else "",
                            field.queryset.model.__name__)
                        )
                    elif hasattr(serializer.Meta.model, key):
                        field_data['help_text'] = ('{}\nRequires/renders pk(id) of {} as integer'.format(
                            field.help_text if field.help_text else "",
                            getattr(serializer.Meta.model, key).field.related_model.__name__)
                        )
                elif isinstance(field, ManyRelatedField):
                    if hasattr(field, 'queryset') and hasattr(field.queryset, 'model'):
                        field_data['help_text'] = ("{}\nRequires/renders list of pk's(id's) of {} objects.".format(
                            field.help_text if field.help_text else "",
                            field.child_relation.queryset.model.__name__)
                        )
                    elif hasattr(serializer.Meta.model, key):
                        field_data['help_text'] = ('{}\nRequires/renders pk(id) of {} as integer'.format(
                            field.help_text if field.help_text else "",
                            getattr(serializer.Meta.model, key).field.related_model.__name__)
                        )

                fields.append(field_data)

        return fields





