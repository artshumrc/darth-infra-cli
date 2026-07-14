from pathlib import Path
import subprocess

from troposphere import Template


def template_to_dict(template: Template) -> dict[str, object]:
    return template.to_dict()


def assert_template_passes_cfn_lint(template: Template, output_path: Path) -> None:
    output_path.write_text(template.to_yaml())
    result = subprocess.run(
        [
            "cfn-lint",
            "--non-zero-exit-code",
            "error",
            "--template",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
