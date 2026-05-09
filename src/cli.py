"""
meshctx CLI 工具
"""
import argparse
import requests
import json
from typing import Optional


BASE_URL = "http://localhost:8000"


def create_project(name: str, description: str):
    """创建新项目"""
    response = requests.post(
        f"{BASE_URL}/projects",
        json={"name": name, "description": description}
    )
    if response.status_code == 200:
        print(f"项目创建成功: {response.json()}")
    else:
        print(f"项目创建失败: {response.text}")


def list_projects():
    """列表所有项目"""
    response = requests.get(f"{BASE_URL}/projects")
    if response.status_code == 200:
        projects = response.json()
        print(f"\n当前项目列表 ({len(projects)}个):")
        for project in projects:
            print(f"  - {project['name']} ({project['id']})")
            print(f"    描述: {project['description']}")
    else:
        print(f"获取项目列表失败: {response.text}")


def start_conversation(project_id: str, title: str):
    """开始新会话"""
    response = requests.post(
        f"{BASE_URL}/conversations",
        json={"project_id": project_id, "title": title}
    )
    if response.status_code == 200:
        print(f"会话开始成功: {response.json()}")
    else:
        print(f"会话开始失败: {response.text}")


def add_message(conversation_id: str, role: str, content: str):
    """添加消息到会话"""
    response = requests.post(
        f"{BASE_URL}/messages",
        json={
            "conversation_id": conversation_id,
            "role": role,
            "content": content
        }
    )
    if response.status_code == 200:
        print(f"消息添加成功")
    else:
        print(f"消息添加失败: {response.text}")


def get_memories(project_id: str):
    """获取项目的记忆"""
    response = requests.get(f"{BASE_URL}/projects/{project_id}/memories")
    if response.status_code == 200:
        memories = response.json()
        print(f"\n项目记忆 ({len(memories)}条):")
        for memory in memories:
            print(f"  - {memory['key']}: {memory['value'][:100]}...")
    else:
        print(f"获取记忆失败: {response.text}")


def health_check():
    """检查服务状态"""
    response = requests.get(f"{BASE_URL}/health")
    if response.status_code == 200:
        health = response.json()
        print(f"服务状态: {health['status']}")
        print(f"项目数量: {health['projects_count']}")
        print(f"会话数量: {health['conversations_count']}")
        print(f"助手数量: {health['agents_count']}")
    else:
        print(f"健康检查失败: {response.text}")


def main():
    parser = argparse.ArgumentParser(description="meshctx CLI 工具")
    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # 创建项目
    create_parser = subparsers.add_parser('create-project', help='创建新项目')
    create_parser.add_argument('name', help='项目名称')
    create_parser.add_argument('description', help='项目描述')
    
    # 列表项目
    subparsers.add_parser('list-projects', help='列表所有项目')
    
    # 开始会话
    conversation_parser = subparsers.add_parser('start-conversation', help='开始新会话')
    conversation_parser.add_argument('project_id', help='项目 ID')
    conversation_parser.add_argument('title', help='会话标题')
    
    # 添加消息
    message_parser = subparsers.add_parser('add-message', help='添加消息')
    message_parser.add_argument('conversation_id', help='会话 ID')
    message_parser.add_argument('role', choices=['user', 'assistant', 'system'], help='消息角色')
    message_parser.add_argument('content', help='消息内容')
    
    # 获取记忆
    memory_parser = subparsers.add_parser('get-memories', help='获取项目记忆')
    memory_parser.add_argument('project_id', help='项目 ID')
    
    # 健康检查
    subparsers.add_parser('health', help='检查服务状态')
    
    args = parser.parse_args()
    
    if args.command == 'create-project':
        create_project(args.name, args.description)
    elif args.command == 'list-projects':
        list_projects()
    elif args.command == 'start-conversation':
        start_conversation(args.project_id, args.title)
    elif args.command == 'add-message':
        add_message(args.conversation_id, args.role, args.content)
    elif args.command == 'get-memories':
        get_memories(args.project_id)
    elif args.command == 'health':
        health_check()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()