#!/usr/bin/env python3
"""
更新构建时间戳脚本
在构建前运行此脚本以更新构建时间
"""
import re
from datetime import datetime

def update_build_time():
    """更新main.py中的BUILD_TIME"""
    file_path = 'backend/main.py'
    
    # 读取文件
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 生成当前时间戳
    current_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # 替换BUILD_TIME
    pattern = r'BUILD_TIME = "[^"]*"'
    replacement = f'BUILD_TIME = "{current_time}"'
    
    new_content = re.sub(pattern, replacement, content)
    
    # 写回文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✓ Updated BUILD_TIME to: {current_time}")

if __name__ == '__main__':
    update_build_time()

