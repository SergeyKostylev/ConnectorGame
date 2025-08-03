
class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}

    def add_node(self, node_name, **attrs):
        if node_name not in self.nodes:
            self.nodes[node_name] = attrs
            self.edges[node_name] = set()
        else:
            self.nodes[node_name].update(attrs)