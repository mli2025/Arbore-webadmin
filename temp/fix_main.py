import re

filepath = r'e:\Arbore\web-admin\backend\main.py'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find start line: "# 方法2：Fallback"
start_line = None
end_line = None
for i, line in enumerate(lines):
    if '方法2' in line and 'Fallback' in line:
        start_line = i
    if start_line is not None and 'docker-compose.yml解析服务失败' in line:
        end_line = i
        break

print(f"start_line={start_line}, end_line={end_line}")
if start_line is None or end_line is None:
    print("ERROR: Could not find section to replace")
    exit(1)

print(f"Replacing lines {start_line+1} to {end_line+1}")
print(f"First old line: {repr(lines[start_line])}")
print(f"Last old line: {repr(lines[end_line])}")

# Get indentation from original
new_section = '''    # 方法2：Fallback - 从docker-compose.yml逐行解析
    if not services:
        project_root = get_project_root()
        docker_compose_path = os.path.join(project_root, "docker-compose.yml")
        
        if os.path.exists(docker_compose_path):
            try:
                with open(docker_compose_path, 'r', encoding='utf-8') as f:
                    compose_lines = f.readlines()
                
                service_blocks = {}
                current_service = None
                for line in compose_lines:
                    stripped = line.rstrip()
                    if stripped and not stripped[0].isspace() and not stripped.startswith('#'):
                        current_service = None
                        continue
                    svc_match = re.match(r'^  ([a-z0-9][a-z0-9-]*)\\s*:', line)
                    if svc_match and not line.startswith('    '):
                        current_service = svc_match.group(1)
                        service_blocks[current_service] = []
                        continue
                    if current_service is not None:
                        service_blocks[current_service].append(line)
                
                for svc_name, block_lines in service_blocks.items():
                    service_block = ''.join(block_lines)
                    
                    ports_match = re.search(r'ports:\\s*\\n\\s*-\\s*"(\\d+):(\\d+)"', service_block)
                    if not ports_match:
                        continue
                    
                    host_port = int(ports_match.group(1))
                    container_port = int(ports_match.group(2))
                    
                    if not (7000 <= host_port <= 7999):
                        continue
                    
                    port = host_port
                    service_metadata = metadata.get(svc_name, {})
                    description = service_metadata.get("description", f"{svc_name}服务")
                    icon = service_metadata.get("icon", "Box")
                    
                    if not service_metadata:
                        comment_match = re.search(r'#\\s*([^\\n]+)', service_block)
                        if comment_match:
                            description = comment_match.group(1).strip()
                            icon_match_inner = re.search(r'\\[icon:([^\\]]+)\\]', description)
                            if icon_match_inner:
                                icon = icon_match_inner.group(1)
                                description = re.sub(r'\\s*\\[icon:[^\\]]+\\]\\s*', '', description)
                            description = re.sub(r'（.*端口.*）', '', description).strip()
                        if not description:
                            description = f"{svc_name}服务"
                    
                    memory_limit_mb = None
                    memory_reservation_mb = None
                    mem_limit_match = re.search(r'mem_limit:\\s*([^\\n]+)', service_block)
                    if mem_limit_match:
                        memory_limit_mb = _parse_memory_to_mb(mem_limit_match.group(1).strip())
                    mem_res_match = re.search(r'mem_reservation:\\s*([^\\n]+)', service_block)
                    if mem_res_match:
                        memory_reservation_mb = _parse_memory_to_mb(mem_res_match.group(1).strip())
                    
                    services.append({
                        "name": svc_name,
                        "port": port,
                        "container_port": container_port,
                        "endpoint": f"/{svc_name}",
                        "description": description,
                        "icon": icon,
                        "memory_limit_mb": memory_limit_mb if (memory_limit_mb and memory_limit_mb > 0) else None,
                        "memory_reservation_mb": memory_reservation_mb if (memory_reservation_mb and memory_reservation_mb > 0) else None,
                        "has_doc": service_metadata.get("has_doc", False) if service_metadata else False
                    })
            except Exception as e:
                print(f"从docker-compose.yml解析服务失败: {e}")
'''

new_lines = [l + '\n' for l in new_section.split('\n')]
# Remove the trailing extra newline
if new_lines and new_lines[-1] == '\n':
    new_lines = new_lines[:-1]

lines[start_line:end_line+1] = new_lines

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done! File updated successfully.")
