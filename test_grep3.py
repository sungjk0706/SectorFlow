import re
with open('/Users/sungjk0706/.gemini/antigravity/brain/01f94509-a199-4dd4-9bce-e8a488b68083/.system_generated/tasks/task-3195.log', 'r') as f:
    for line in f:
        if '캐시된 레이아웃 없음' in line:
            print(line.strip())
