from django import template
register = template.Library()


@register.simple_tag(name="getattrl")
def getattribute_lang(obj, field_name, lang_code):
    return getattr(obj, '{0}_{1}'.format(field_name, lang_code))


@register.filter("getattr")
def getattribute(obj, field_name):
    return getattr(obj, field_name)


@register.simple_tag(name="uptodate")
def is_uptodate(obj, field, lang, default_language):
    if hasattr(obj, '{0}_{1}_last_modified'.format(field, lang)):
        last_modified_en = getattr(obj, field, default_language)
        last_modified_lang = getattr(obj, field, lang)

        return last_modified_en <= last_modified_lang

    # If there is no last_modified field, we have to guess that is up to date
    return True
