# -*- coding: utf-8 -*-
from copy import deepcopy

import django
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.options import BaseModelAdmin, flatten_fieldsets, InlineModelAdmin
from django import forms

# Ensure that models are registered for translation before TranslationAdmin
# runs. The import is supposed to resolve a race condition between model import
# and translation registration in production (see issue #19).
if django.VERSION < (1, 7):
    from django.contrib.contenttypes.generic import GenericTabularInline
    from django.contrib.contenttypes.generic import GenericStackedInline
    import modeltranslation.models  # NOQA
else:
    from django.contrib.contenttypes.admin import GenericTabularInline
    from django.contrib.contenttypes.admin import GenericStackedInline
from modeltranslation import settings as mt_settings
from modeltranslation.translator import translator
from modeltranslation.utils import (
    get_translation_fields, build_css_class, build_localized_fieldname, get_language,
    get_language_bidi, unique)
from modeltranslation.widgets import ClearableWidgetWrapper

# ##################################################################
# ##################################################################
# ###################### Translation panel #########################
# ##################################################################
# ##################################################################
import json
from django.conf.urls import patterns, url
from django.template.response import TemplateResponse
from django.core.urlresolvers import reverse
from django.contrib.admin import SimpleListFilter
from django.http import HttpResponse
from modeltranslation.templatetags.modeltranslation_tags import is_uptodate
from django.utils import timezone

class JSONResponse(HttpResponse):
    """
    An HttpResponse that renders its content into JSON.
    """
    def __init__(self, data, **kwargs):
        content = json.dumps(data)
        kwargs['content_type'] = 'application/json'
        super(JSONResponse, self).__init__(content, **kwargs)


class LanguageFilter(SimpleListFilter):
    title = 'language'
    parameter_name = 'lang'

    def lookups(self, request, model_admin):
        return settings.LANGUAGES

    def queryset(self, request, queryset):
        return queryset


class TranslationStatusFilter(SimpleListFilter):
    title = 'translation'
    parameter_name = 'translation'

    def lookups(self, request, model_admin):
        return (
            ('updated', _('Updated')),
            ('missing', _('Missing')),
            ('not-updated', _('Missing')),
            ('equal', _('Equal')),
            )

    def queryset(self, request, queryset):
        return queryset


class ModelTranslationPanelMixin(object):

    model_translations_template_name = 'admin/modeltranslation/model_translations.html'

    translation_field_order = None

    def get_model_info(self):
        # module_name is renamed to model_name in Django 1.8
        app_label = self.model._meta.app_label
        try:
            return (app_label, self.model._meta.model_name,)
        except AttributeError:
            return (app_label, self.model._meta.module_name,)

    def get_urls(self):
        urls = super(ModelTranslationPanelMixin, self).get_urls()
        info = self.get_model_info()
        my_urls = patterns(
            '',
            url(r'^update_translations/$',
                self.admin_site.admin_view(self.update_translations),
                name='%s_%s_update_translations' % info),
            url(r'^process_translations/$',
                self.admin_site.admin_view(self.process_translations),
                name='%s_%s_process_translations' % info),
            url(r'^translations/$',
                self.admin_site.admin_view(self.translations),
                name='%s_%s_translations' % info),
        )
        return my_urls + urls

    def update_translations(self, request, *args, **kwargs):
        # We have to save the updated field
        data = json.loads(request.body)

        current_lang = data['lang']

        field_name = data['name']

        instance = self.model.objects.get(pk=data['instance'])

        last_modified = 'Unknown'
        if hasattr(instance, '{0}_last_modified'.format(field_name)):
            now = timezone.now()
            last_modified = now.strftime('%d-%m-%Y %H:%M:%S')
            setattr(instance, '{0}_last_modified'.format(field_name), now)
            instance.save()

        # Get the new status
        new_status = is_uptodate(instance, field_name, current_lang, mt_settings.DEFAULT_LANGUAGE)

        return JSONResponse({
            'status': new_status,
            'instance_id': instance.pk,
            'field_name': field_name,
            'last_modified': last_modified,
            })

    # This is the actual view function that will be executed when accessing the panel
    def process_translations(self, request, *args, **kwargs):
        # We have to save the updated field
        data = json.loads(request.body)

        current_lang = data['lang']

        field_name = data['name']
        field_value = data['value']

        instance = self.model.objects.get(pk=data['instance'])

        setattr(instance, field_name, field_value)
        instance.save()

        last_modified = 'Unknown'
        if hasattr(instance, '{0}_last_modified'.format(field_name)):
            last_modified = getattr(instance, '{0}_last_modified'.format(field_name))
            last_modified = last_modified.strftime('%d-%m-%Y %H:%M:%S')

        # Get the new status
        new_status = is_uptodate(instance, field_name, current_lang, mt_settings.DEFAULT_LANGUAGE)

        return JSONResponse({
            'status': new_status,
            'instance_id': instance.pk,
            'field_name': field_name,
            'last_modified': last_modified,
            })

    def translations(self, request, extra_context=None):
        context = {}

        context['opts'] = self.model._meta
        context['trans_opts'] = self.trans_opts
        info = self.get_model_info()
        # context['process_url'] = reverse('%s_%s_process_translations' % info)

        context['AVAILABLE_LANGUAGES'] = mt_settings.AVAILABLE_LANGUAGES
        context['LANGUAGES'] = settings.LANGUAGES
        context['DEFAULT_LANGUAGE'] = mt_settings.DEFAULT_LANGUAGE

        context['model'] = self.model
        field_names = self.trans_opts.get_field_names()
        if self.translation_field_order is not None:
            field_names = list(self.translation_field_order) + [x for x in field_names if x not in self.translation_field_order]

        context['trans_fields'] = field_names
        context['trans_monitored_fields'] = self.trans_opts.monitored_fields

        query_parameters = request.GET.copy()

        if 'lang' in query_parameters:
            current_lang = query_parameters.get('lang')
            context['trans_language'] = current_lang

            request.GET = query_parameters

            # Get the formset
            self.list_editable = list(['{0}_{1}'.format(field, current_lang) for field in field_names])

        """
            From django.contrib.admin.options.BaseModelAdmin
        """
        from django.contrib.admin.options import *
        from django.contrib.admin.views.main import ERROR_FLAG
        from django.utils.translation import ugettext as _

        opts = self.model._meta
        app_label = opts.app_label
        if not self.has_change_permission(request, None):
            raise PermissionDenied

        list_display = self.get_list_display(request)
        list_display_links = self.get_list_display_links(request, list_display)
        list_filter = self.get_list_filter(request)

        # Include the language filter as a list_filter
        list_filter = self.list_filter + (LanguageFilter,)

        # Check actions to see if any are available on this changelist
        actions = self.get_actions(request)
        if actions:
            # Add the action checkboxes if there are any actions available.
            list_display = ['action_checkbox'] + list(list_display)

        ChangeList = self.get_changelist(request)
        try:
            cl = ChangeList(request, self.model, list_display,
                list_display_links, list_filter, self.date_hierarchy,
                self.search_fields, self.list_select_related,
                self.list_per_page, self.list_max_show_all, self.list_editable,
                self)
        except IncorrectLookupParameters:
            # Wacky lookup parameters were given, so redirect to the main
            # changelist page, without parameters, and pass an 'invalid=1'
            # parameter via the query string. If wacky parameters were given
            # and the 'invalid=1' parameter was already in the query string,
            # something is screwed up with the database, so display an error
            # page.
            if ERROR_FLAG in request.GET.keys():
                return SimpleTemplateResponse('admin/invalid_setup.html', {
                    'title': _('Database error'),
                })
            return HttpResponseRedirect(request.path + '?' + ERROR_FLAG + '=1')

        # If the request was POSTed, this might be a bulk action or a bulk
        # edit. Try to look up an action or confirmation first, but if this
        # isn't an action the POST will fall through to the bulk edit check,
        # below.
        action_failed = False
        selected = request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)

        # Actions with no confirmation
        if (actions and request.method == 'POST' and
                'index' in request.POST and '_save' not in request.POST):
            if selected:
                response = self.response_action(request, queryset=cl.get_queryset(request))
                if response:
                    return response
                else:
                    action_failed = True
            else:
                msg = _("Items must be selected in order to perform "
                        "actions on them. No items have been changed.")
                self.message_user(request, msg, messages.WARNING)
                action_failed = True

        # Actions with confirmation
        if (actions and request.method == 'POST' and
                helpers.ACTION_CHECKBOX_NAME in request.POST and
                'index' not in request.POST and '_save' not in request.POST):
            if selected:
                response = self.response_action(request, queryset=cl.get_queryset(request))
                if response:
                    return response
                else:
                    action_failed = True

        # If we're allowing changelist editing, we need to construct a formset
        # for the changelist given all the fields to be edited. Then we'll
        # use the formset to validate/process POSTed data.
        formset = cl.formset = None

        # Handle POSTed bulk-edit data.
        if (request.method == "POST" and cl.list_editable and
                '_save' in request.POST and not action_failed):
            FormSet = self.get_changelist_formset(request)
            formset = cl.formset = FormSet(request.POST, request.FILES, queryset=cl.result_list)
            if formset.is_valid():
                changecount = 0
                for form in formset.forms:
                    if form.has_changed():
                        obj = self.save_form(request, form, change=True)
                        self.save_model(request, obj, form, change=True)
                        self.save_related(request, form, formsets=[], change=True)
                        change_msg = self.construct_change_message(request, form, None)
                        self.log_change(request, obj, change_msg)
                        changecount += 1

                if changecount:
                    if changecount == 1:
                        name = force_text(opts.verbose_name)
                    else:
                        name = force_text(opts.verbose_name_plural)
                    msg = ungettext("%(count)s %(name)s was changed successfully.",
                                    "%(count)s %(name)s were changed successfully.",
                                    changecount) % {'count': changecount,
                                                    'name': name,
                                                    'obj': force_text(obj)}
                    self.message_user(request, msg, messages.SUCCESS)

                return HttpResponseRedirect(request.get_full_path())

        # Handle GET -- construct a formset for display.
        elif cl.list_editable:
            FormSet = self.get_changelist_formset(request)
            formset = cl.formset = FormSet(queryset=cl.result_list)

        # Build the list of media to be used by the formset.
        if formset:
            media = self.media + formset.media
        else:
            media = self.media

        # Build the action form and populate it with available actions.
        if actions:
            action_form = self.action_form(auto_id=None)
            action_form.fields['action'].choices = self.get_action_choices(request)
        else:
            action_form = None

        selection_note_all = ungettext('%(total_count)s selected',
            'All %(total_count)s selected', cl.result_count)
        context.update({
            'module_name': force_text(opts.verbose_name_plural),
            'selection_note': _('0 of %(cnt)s selected') % {'cnt': len(cl.result_list)},
            'selection_note_all': selection_note_all % {'total_count': cl.result_count},
            'title': cl.title,
            'is_popup': cl.is_popup,
            'cl': cl,
            'media': media,
            'has_add_permission': self.has_add_permission(request),
            'opts': cl.opts,
            'app_label': app_label,
            'action_form': action_form,
            'actions_on_top': self.actions_on_top,
            'actions_on_bottom': self.actions_on_bottom,
            'actions_selection_counter': self.actions_selection_counter,
            'preserved_filters': self.get_preserved_filters(request),
        })
        context.update(extra_context or {})

        return TemplateResponse(request, [self.model_translations_template_name],
                                context, current_app=self.admin_site.name)


# ##################################################################
# ##################################################################
# ###################### Original content ##########################
# ##################################################################
# ##################################################################

class TranslationBaseModelAdmin(ModelTranslationPanelMixin, BaseModelAdmin):
    _orig_was_required = {}
    both_empty_values_fields = ()

    def __init__(self, *args, **kwargs):
        super(TranslationBaseModelAdmin, self).__init__(*args, **kwargs)
        self.trans_opts = translator.get_options_for_model(self.model)
        self._patch_prepopulated_fields()

    def _declared_fieldsets(self):
        # Take custom modelform fields option into account
        if not self.fields and hasattr(self.form, '_meta') and self.form._meta.fields:
            self.fields = self.form._meta.fields
        if self.fieldsets:
            return self._patch_fieldsets(self.fieldsets)
        elif self.fields:
            return [(None, {'fields': self.replace_orig_field(self.fields)})]
        return None
    declared_fieldsets = property(_declared_fieldsets)

    def formfield_for_dbfield(self, db_field, **kwargs):
        field = super(TranslationBaseModelAdmin, self).formfield_for_dbfield(db_field, **kwargs)
        self.patch_translation_field(db_field, field, **kwargs)
        return field

    def patch_translation_field(self, db_field, field, **kwargs):
        if db_field.name in self.trans_opts.fields:
            if field.required:
                field.required = False
                field.blank = True
                self._orig_was_required['%s.%s' % (db_field.model._meta, db_field.name)] = True

        # For every localized field copy the widget from the original field
        # and add a css class to identify a modeltranslation widget.
        try:
            orig_field = db_field.translated_field
        except AttributeError:
            pass
        else:
            orig_formfield = self.formfield_for_dbfield(orig_field, **kwargs)
            field.widget = deepcopy(orig_formfield.widget)
            if orig_field.name in self.both_empty_values_fields:
                from modeltranslation.forms import NullableField, NullCharField
                form_class = field.__class__
                if issubclass(form_class, NullCharField):
                    # NullableField don't work with NullCharField
                    form_class.__bases__ = tuple(
                        b for b in form_class.__bases__ if b != NullCharField)
                field.__class__ = type(
                    'Nullable%s' % form_class.__name__, (NullableField, form_class), {})
            if ((db_field.empty_value == 'both' or orig_field.name in self.both_empty_values_fields)
                    and isinstance(field.widget, (forms.TextInput, forms.Textarea))):
                field.widget = ClearableWidgetWrapper(field.widget)
            css_classes = field.widget.attrs.get('class', '').split(' ')
            css_classes.append('mt')
            # Add localized fieldname css class
            css_classes.append(build_css_class(db_field.name, 'mt-field'))
            # Add mt-bidi css class if language is bidirectional
            if(get_language_bidi(db_field.language)):
                css_classes.append('mt-bidi')
            if db_field.language == mt_settings.DEFAULT_LANGUAGE:
                # Add another css class to identify a default modeltranslation widget
                css_classes.append('mt-default')
                if (orig_formfield.required or self._orig_was_required.get(
                        '%s.%s' % (orig_field.model._meta, orig_field.name))):
                    # In case the original form field was required, make the
                    # default translation field required instead.
                    orig_formfield.required = False
                    orig_formfield.blank = True
                    field.required = True
                    field.blank = False
                    # Hide clearable widget for required fields
                    if isinstance(field.widget, ClearableWidgetWrapper):
                        field.widget = field.widget.widget
            field.widget.attrs['class'] = ' '.join(css_classes)

    def _exclude_original_fields(self, exclude=None):
        if exclude is None:
            exclude = tuple()
        if exclude:
            exclude_new = tuple(exclude)
            return exclude_new + tuple(self.trans_opts.fields.keys())
        return tuple(self.trans_opts.fields.keys())

    def replace_orig_field(self, option):
        """
        Replaces each original field in `option` that is registered for
        translation by its translation fields.

        Returns a new list with replaced fields. If `option` contains no
        registered fields, it is returned unmodified.

        >>> self = TranslationAdmin()  # PyFlakes
        >>> print(self.trans_opts.fields.keys())
        ['title',]
        >>> get_translation_fields(self.trans_opts.fields.keys()[0])
        ['title_de', 'title_en']
        >>> self.replace_orig_field(['title', 'url'])
        ['title_de', 'title_en', 'url']

        Note that grouped fields are flattened. We do this because:

            1. They are hard to handle in the jquery-ui tabs implementation
            2. They don't scale well with more than a few languages
            3. It's better than not handling them at all (okay that's weak)

        >>> self.replace_orig_field((('title', 'url'), 'email', 'text'))
        ['title_de', 'title_en', 'url_de', 'url_en', 'email_de', 'email_en', 'text']
        """
        if option:
            option_new = list(option)
            for opt in option:
                if opt in self.trans_opts.fields:
                    index = option_new.index(opt)
                    option_new[index:index + 1] = get_translation_fields(opt)
                elif isinstance(opt, (tuple, list)) and (
                        [o for o in opt if o in self.trans_opts.fields]):
                    index = option_new.index(opt)
                    option_new[index:index + 1] = self.replace_orig_field(opt)
            option = option_new
        return option

    def _patch_fieldsets(self, fieldsets):
        if fieldsets:
            fieldsets_new = list(fieldsets)
            for (name, dct) in fieldsets:
                if 'fields' in dct:
                    dct['fields'] = self.replace_orig_field(dct['fields'])
            fieldsets = fieldsets_new
        return fieldsets

    def _patch_prepopulated_fields(self):
        def localize(sources, lang):
            "Append lang suffix (if applicable) to field list"
            def append_lang(source):
                if source in self.trans_opts.fields:
                    return build_localized_fieldname(source, lang)
                return source
            return tuple(map(append_lang, sources))

        prepopulated_fields = {}
        for dest, sources in self.prepopulated_fields.items():
            if dest in self.trans_opts.fields:
                for lang in mt_settings.AVAILABLE_LANGUAGES:
                    key = build_localized_fieldname(dest, lang)
                    prepopulated_fields[key] = localize(sources, lang)
            else:
                lang = mt_settings.PREPOPULATE_LANGUAGE or get_language()
                prepopulated_fields[dest] = localize(sources, lang)
        self.prepopulated_fields = prepopulated_fields

    def _get_form_or_formset(self, request, obj, **kwargs):
        """
        Generic code shared by get_form and get_formset.
        """
        if self.exclude is None:
            exclude = []
        else:
            exclude = list(self.exclude)
        exclude.extend(self.get_readonly_fields(request, obj))
        if not self.exclude and hasattr(self.form, '_meta') and self.form._meta.exclude:
            # Take the custom ModelForm's Meta.exclude into account only if the
            # ModelAdmin doesn't define its own.
            exclude.extend(self.form._meta.exclude)
        # If exclude is an empty list we pass None to be consistant with the
        # default on modelform_factory
        exclude = self.replace_orig_field(exclude) or None
        exclude = self._exclude_original_fields(exclude)
        kwargs.update({'exclude': exclude})

        return kwargs

    def _get_fieldsets_pre_form_or_formset(self):
        """
        Generic get_fieldsets code, shared by
        TranslationAdmin and TranslationInlineModelAdmin.
        """
        return self._declared_fieldsets()

    def _get_fieldsets_post_form_or_formset(self, request, form, obj=None):
        """
        Generic get_fieldsets code, shared by
        TranslationAdmin and TranslationInlineModelAdmin.
        """
        base_fields = self.replace_orig_field(form.base_fields.keys())
        fields = base_fields + list(self.get_readonly_fields(request, obj))
        return [(None, {'fields': self.replace_orig_field(fields)})]

    def get_translation_field_excludes(self, exclude_languages=None):
        """
        Returns a tuple of translation field names to exclude based on
        `exclude_languages` arg.
        TODO: Currently unused?
        """
        if exclude_languages is None:
            exclude_languages = []
        excl_languages = []
        if exclude_languages:
            excl_languages = exclude_languages
        exclude = []
        for orig_fieldname, translation_fields in self.trans_opts.fields.items():
            for tfield in translation_fields:
                if tfield.language in excl_languages and tfield not in exclude:
                    exclude.append(tfield)
        return tuple(exclude)

    def get_readonly_fields(self, request, obj=None):
        """
        Hook to specify custom readonly fields.
        """
        return self.replace_orig_field(self.readonly_fields)


class TranslationAdmin(TranslationBaseModelAdmin, admin.ModelAdmin):
    # TODO: Consider addition of a setting which allows to override the fallback to True
    group_fieldsets = False

    def __init__(self, *args, **kwargs):
        super(TranslationAdmin, self).__init__(*args, **kwargs)
        self._patch_list_editable()

    def _patch_list_editable(self):
        if self.list_editable:
            editable_new = list(self.list_editable)
            display_new = list(self.list_display)
            for field in self.list_editable:
                if field in self.trans_opts.fields:
                    index = editable_new.index(field)
                    display_index = display_new.index(field)
                    translation_fields = get_translation_fields(field)
                    editable_new[index:index + 1] = translation_fields
                    display_new[display_index:display_index + 1] = translation_fields
            self.list_editable = editable_new
            self.list_display = display_new

    def _group_fieldsets(self, fieldsets):
        # Fieldsets are not grouped by default. The function is activated by
        # setting TranslationAdmin.group_fieldsets to True. If the admin class
        # already defines a fieldset, we leave it alone and assume the author
        # has done whatever grouping for translated fields they desire.
        if not self.declared_fieldsets and self.group_fieldsets is True:
            flattened_fieldsets = flatten_fieldsets(fieldsets)

            # Create a fieldset to group each translated field's localized fields
            untranslated_fields = [
                f.name for f in self.opts.fields if (
                    # Exclude the primary key field
                    f is not self.opts.auto_field
                    # Exclude non-editable fields
                    and f.editable
                    # Exclude the translation fields
                    and not hasattr(f, 'translated_field')
                    # Honour field arguments. We rely on the fact that the
                    # passed fieldsets argument is already fully filtered
                    # and takes options like exclude into account.
                    and f.name in flattened_fieldsets
                )
            ]
            # TODO: Allow setting a label
            fieldsets = [('', {'fields': untranslated_fields},)] if untranslated_fields else []

            temp_fieldsets = {}
            for orig_field, trans_fields in self.trans_opts.fields.items():
                trans_fieldnames = [f.name for f in sorted(trans_fields, key=lambda x: x.name)]
                if any(f in trans_fieldnames for f in flattened_fieldsets):
                    # Extract the original field's verbose_name for use as this
                    # fieldset's label - using ugettext_lazy in your model
                    # declaration can make that translatable.
                    label = self.model._meta.get_field(orig_field).verbose_name.capitalize()
                    temp_fieldsets[orig_field] = (label, {
                        'fields': trans_fieldnames,
                        'classes': ('mt-fieldset',)
                    })

            fields_order = unique(f.translated_field.name for f in self.opts.fields if
                                  hasattr(f, 'translated_field') and f.name in flattened_fieldsets)
            for field_name in fields_order:
                fieldsets.append(temp_fieldsets.pop(field_name))
            assert not temp_fieldsets  # cleaned

        return fieldsets

    def get_form(self, request, obj=None, **kwargs):
        kwargs = self._get_form_or_formset(request, obj, **kwargs)
        return super(TranslationAdmin, self).get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if self.declared_fieldsets:
            return self._get_fieldsets_pre_form_or_formset()
        return self._group_fieldsets(
            self._get_fieldsets_post_form_or_formset(
                request, self.get_form(request, obj, fields=None), obj))


class TranslationInlineModelAdmin(TranslationBaseModelAdmin, InlineModelAdmin):
    def get_formset(self, request, obj=None, **kwargs):
        kwargs = self._get_form_or_formset(request, obj, **kwargs)
        return super(TranslationInlineModelAdmin, self).get_formset(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        # FIXME: If fieldsets are declared on an inline some kind of ghost
        # fieldset line with just the original model verbose_name of the model
        # is displayed above the new fieldsets.
        if self.declared_fieldsets:
            return self._get_fieldsets_pre_form_or_formset()
        form = self.get_formset(request, obj, fields=None).form
        return self._get_fieldsets_post_form_or_formset(request, form, obj)


class TranslationTabularInline(TranslationInlineModelAdmin, admin.TabularInline):
    pass


class TranslationStackedInline(TranslationInlineModelAdmin, admin.StackedInline):
    pass


class TranslationGenericTabularInline(TranslationInlineModelAdmin, GenericTabularInline):
    pass


class TranslationGenericStackedInline(TranslationInlineModelAdmin, GenericStackedInline):
    pass


class TabbedDjango15JqueryTranslationAdmin(TranslationAdmin):
    """
    Convenience class which includes the necessary static files for tabbed
    translation fields. Reuses Django's internal jquery version. Django 1.5
    included jquery 1.4.2 which is known to work well with jquery-ui 1.8.2.
    """
    class Media:
        js = (
            'modeltranslation/js/force_jquery.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.8.2/jquery-ui.min.js',
            '//cdn.jsdelivr.net/jquery.mb.browser/0.1/jquery.mb.browser.min.js',
            'modeltranslation/js/tabbed_translation_fields.js',
        )
        css = {
            'all': ('modeltranslation/css/tabbed_translation_fields.css',),
        }


class TabbedDjangoJqueryTranslationAdmin(TranslationAdmin):
    """
    Convenience class which includes the necessary media files for tabbed
    translation fields. Reuses Django's internal jquery version.
    """
    class Media:
        js = (
            'modeltranslation/js/force_jquery.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.11.2/jquery-ui.min.js',
            '//cdn.jsdelivr.net/jquery.mb.browser/0.1/jquery.mb.browser.min.js',
            'modeltranslation/js/tabbed_translation_fields.js',
        )
        css = {
            'all': ('modeltranslation/css/tabbed_translation_fields.css',),
        }


class TabbedExternalJqueryTranslationAdmin(TranslationAdmin):
    """
    Convenience class which includes the necessary media files for tabbed
    translation fields. Loads recent jquery version from a cdn.
    """
    class Media:
        js = (
            '//ajax.googleapis.com/ajax/libs/jquery/1.11.1/jquery.min.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.11.2/jquery-ui.min.js',
            '//cdn.jsdelivr.net/jquery.mb.browser/0.1/jquery.mb.browser.min.js',
            'modeltranslation/js/tabbed_translation_fields.js',
        )
        css = {
            'screen': ('modeltranslation/css/tabbed_translation_fields.css',),
        }


if django.VERSION < (1, 6):
    TabbedTranslationAdmin = TabbedDjango15JqueryTranslationAdmin
else:
    TabbedTranslationAdmin = TabbedDjangoJqueryTranslationAdmin
