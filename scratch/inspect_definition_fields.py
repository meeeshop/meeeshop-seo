import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query {
      __type(name: "MetafieldDefinition") {
        fields {
          name
          type {
            name
            kind
          }
        }
      }
    }
    """
    res = run_graphql(query)
    fields = res.get("data", {}).get("__type", {}).get("fields", [])
    print("MetafieldDefinition fields:")
    for f in fields:
        print(f" - {f['name']} ({f['type']['name']} / {f['type']['kind']})")

if __name__ == "__main__":
    main()
