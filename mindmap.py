class Node:
    def __init__(self, name, level):
        self.name = name
        self.level = level
        self.children = []

    def add_child(self, child):
        self.children.append(child)

    def display(self):
        print('  ' * self.level + self.name)
        for child in self.children:
            child.display()

def parse_mindmap(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()

    root = None
    node_stack = []
    prev_level = -1

    for line in lines:
        line = line.strip()
        level = line.count('   ')
        name = line.strip()

        node = Node(name, level)

        if level <= prev_level:
            for _ in range(prev_level - level + 1):
                if node_stack:
                    node_stack.pop()

        if node_stack:
            node_stack[-1].add_child(node)

        node_stack.append(node)
        prev_level = level

        if root is None:
            root = node

    return root

if __name__ == '__main__':
    mindmap_path = 'mindmap.txt'
    mindmap_root = parse_mindmap(mindmap_path)
    mindmap_root.display()
