
class GraphHelper:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def add_node(self, node_name, **attrs):
        if node_name not in self.nodes:
            self.nodes[node_name] = attrs
            self.edges[node_name] = set()
        else:
            self.nodes[node_name].update(attrs)

    def add_edge(self, node1, node2):
        if node1 not in self.nodes or node2 not in self.nodes:
            raise ValueError("Both nodes must be added before joining.")
        self.edges[node1].add(node2)
        self.edges[node2].add(node1)

    def has_edge(self, node1, node2):
        return node1 in self.edges and node2 in self.edges[node1]

    def remove_edge(self, node1, node2):
        if self.has_edge(node1, node2):
            self.edges[node1].remove(node2)
            self.edges[node2].remove(node1)

    def has_path(self, start, end):
        if start not in self.nodes or end not in self.nodes:
            return False

        visited = set()
        stack = [start]

        while stack:
            current = stack.pop()
            if current == end:
                return True
            if current in visited:
                continue
            visited.add(current)
            stack.extend(self.edges[current] - visited)

        return False