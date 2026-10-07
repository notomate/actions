from __future__ import annotations

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from common import ActionError, Settings, get_input, markdown_escape, output, parse_data, publish, run


def number(value, spec: str = ",.2f", missing: str = "N/A") -> str:
    return missing if value is None else format(value, spec)


def table_cell(value) -> str:
    return markdown_escape(str(value)).replace("\r", " ").replace("\n", " ")


def environment() -> SandboxedEnvironment:
    # Templates come from the workflow author; the sandbox still blocks attribute escapes.
    # trim/lstrip blocks keep {% %} lines from adding blank lines inside loops, e.g. between table rows.
    env = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True,
                               trim_blocks=True, lstrip_blocks=True)
    env.filters.update(md=lambda value: markdown_escape(str(value)), md_cell=table_cell, number=number)
    return env


def render(title_template: str, content_template: str, data: dict) -> tuple[str, str]:
    env = environment()
    try:
        title = env.from_string(title_template).render(data)
        content = env.from_string(content_template).render(data)
    except TemplateError as exc:
        raise ActionError(f"Note template failed: {exc.message or type(exc).__name__}") from None
    title = " ".join(title.split())
    if not title:
        raise ActionError("The rendered note title is empty.")
    if not content.strip():
        # e.g. the default {{ content }} after a claude step that dropped the content field.
        raise ActionError("The rendered note body is empty; set template or check that data has content.")
    return title, content


def main():
    settings = Settings.read()
    data = parse_data(get_input("data"))
    title, content = render(get_input("title", "{{ title }}"), get_input("template", "{{ content }}"), data)
    publish(settings, title, content)
    output("conclusion", "success")


if __name__ == "__main__":
    run(main)
