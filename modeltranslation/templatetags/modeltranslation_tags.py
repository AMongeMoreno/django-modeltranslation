from django import template
register = template.Library()


@register.filter
def pdb(element):
    import ipdb; ipdb.set_trace()
    return element


@register.simple_tag(name="getattrl")
def getattribute_lang(obj, field_name, lang_code):
    return getattr(obj, '{0}_{1}'.format(field_name, lang_code), None) or ''


@register.simple_tag()
def get_widget(form, field_name):
    field = form.fields[field_name]
    return field.widget


@register.filter("getattr")
def getattribute(obj, field_name):
    return getattr(obj, field_name) or ''


@register.simple_tag(name="is_uptodate")
def is_uptodate(obj, field, lang, default_language):
    if hasattr(obj, '{0}_{1}_last_modified'.format(field, lang)):
        field_value_en = getattr(obj, '{0}_{1}'.format(field, default_language))
        field_value_lang = getattr(obj, '{0}_{1}'.format(field, lang))
        # Check if the content is equal to the default one
        if field_value_lang == field_value_en:
            return 'equal'

        # Finally check if is None and the default is not
        if field_value_lang is None and field_value_en:
            return 'missing'

        last_modified_en = getattr(obj, '{0}_{1}_last_modified'.format(field, default_language))
        last_modified_lang = getattr(obj, '{0}_{1}_last_modified'.format(field, lang))

        # If this language was modified before the english one
        if last_modified_lang <= last_modified_en:
            return 'not-updated'

    # If there is no last_modified field, we have to guess that is up to date
    return 'updated'
