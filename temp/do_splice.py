import sys

main_path = r'e:\Arbore\web-admin\backend\main.py'
replacement_path = r'e:\Arbore\web-admin\temp\method2_replacement.py'

with open(main_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open(replacement_path, 'r', encoding='utf-8') as f:
    replacement = f.read()

start_line = None
end_line = None
for i, line in enumerate(lines):
    if start_line is None and 'Fallback' in line and 'docker-compose' in line:
        start_line = i
    if start_line is not None and 'docker-compose.yml' in line and '解析服务失败' in line:
        end_line = i
        break

if start_line is None or end_line is None:
    print(f"ERROR: start={start_line} end={end_line}")
    sys.exit(1)

print(f"Replacing lines {start_line+1}-{end_line+1} ({end_line-start_line+1} lines)")

new_lines = lines[:start_line] + [replacement + '\n'] + lines[end_line+1:]

with open(main_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("SUCCESS: main.py updated")
