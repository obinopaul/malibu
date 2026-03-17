import sys
from pathlib import Path

dir_path = Path(r"C:\Users\pault\.gemini\antigravity\brain\bf24489c-ef83-40c3-96f0-d1c1b4ed76ce")

output_file = dir_path / "detailed_draft_cli.md"

parts = [
    dir_path / "draft_cli.md",
    dir_path / "draft_cli_part2.md",
    dir_path / "draft_cli_part3.md",
    dir_path / "draft_cli_part4.md",
]

with open(output_file, "w", encoding="utf-8") as outfile:
    for part in parts:
        with open(part, "r", encoding="utf-8") as infile:
            outfile.write(infile.read())
            outfile.write("\n\n")

print(f"Successfully merged {len(parts)} parts into {output_file}")
