from django import template
from datetime import timedelta
from django.utils.safestring import mark_for_escaping
register = template.Library()


@register.filter
def pdb(element):
    import ipdb; ipdb.set_trace()
    return element


@register.simple_tag(name="getattrl")
def getattribute_lang(obj, field_name, lang_code):
    return getattr(obj, '{0}_{1}'.format(field_name, lang_code), None) or ''


@register.simple_tag(name="getlastmodifiedl")
def getlastmodified_lang(obj, field_name, lang_code):
    last_modified = getattr(obj, '{0}_{1}_last_modified'.format(field_name, lang_code), None)
    if last_modified is not None:
        last_modified = last_modified.strftime('%d-%m-%Y %H:%M:%S')
    return last_modified or 'Unknown'


@register.simple_tag()
def get_widget(form, field_name):
    field = form.fields[field_name]
    return field.widget


@register.filter("getattr")
def getattribute(obj, field_name):
    return getattr(obj, field_name) or ''


@register.simple_tag(name="is_uptodate")
def is_uptodate(obj, field, lang, default_language):
    status = []

    field_value_en = getattr(obj, '{0}_{1}'.format(field, default_language))
    field_value_lang = getattr(obj, '{0}_{1}'.format(field, lang))
    # import ipdb; ipdb.set_trace()
    # Finally check if is None and the default is not
    if not field_value_lang and field_value_en:
        status.append('missing')
    # import ipdb; ipdb.set_trace()
    # Check if the content is equal to the default one
    if (field_value_lang or '') == (field_value_en or ''):
        status.append('equal')

    if hasattr(obj, '{0}_{1}_last_modified'.format(field, lang)):
        last_modified_en = getattr(obj, '{0}_{1}_last_modified'.format(field, default_language))
        last_modified_lang = getattr(obj, '{0}_{1}_last_modified'.format(field, lang))

        # If this language was modified before the english one
        if last_modified_lang - last_modified_en < timedelta(seconds=30):
            status.append('not-updated')
        else:
            status.append('updated')
    else:
        # If there is no last_modified field, we have to guess that is up to date
        status.append('updated')

    # Return all the status labels:
    return ' '.join(status)
