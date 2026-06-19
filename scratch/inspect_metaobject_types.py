import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query GetDefinitions($ids: [ID!]!) {
      nodes(ids: $ids) {
        ... on MetaobjectDefinition {
          id
          name
          type
        }
      }
    }
    """
    res = run_graphql(query, {
        "ids": [
            "gid://shopify/MetaobjectDefinition/1728282795",
            "gid://shopify/MetaobjectDefinition/5178687659",
            "gid://shopify/MetaobjectDefinition/5178654891"
        ]
    })
    nodes = res.get("data", {}).get("nodes", [])
    for node in nodes:
        if node:
            print(f"ID: {node['id']:<50} Name: {node['name']:<25} Type: {node['type']}")

if __name__ == "__main__":
    main()
