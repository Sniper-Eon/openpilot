from importlib.resources import files


def fallback_font_characters(language: str, extra_characters: str = "") -> set[str]:
  """Collect every glyph requested when loading a language fallback font."""
  translations_dir = files("openpilot.selfdrive.ui").joinpath("translations")
  characters = set(map(chr, range(32, 127))) | set(extra_characters)
  characters.update(translations_dir.joinpath(f"app_{language}.po").read_text(encoding="utf-8"))

  # Onroad alerts originate in selfdrived, outside of the normal UI PO extraction.
  from openpilot.selfdrive.ui.onroad.alert_localizer import localized_alert_characters
  characters.update(localized_alert_characters(language))
  if language in ('zh-CHS', 'zh-CHT'):
    from openpilot.sunnypilot.navassist.settings import SETTING_SPECS
    for spec in SETTING_SPECS.values():
      characters.update(spec.title + spec.description + spec.unit)
    characters.update('手机导航辅助独立日志下载设置状态已保存至本机使用默认设置读取失败网页浏览器打开此地址停车时可调整下次导航动作使用新设置以下设置控制设备如何使用导航信息选择日志与普通日志分开不包含视频')
  characters.difference_update({"\n", "\r", "\t"})
  return characters
