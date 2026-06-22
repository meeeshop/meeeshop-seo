import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def main():
    query = """
    query {
      __type(name: "QueryRoot") {
        fields {
          name
          args {
            name
            type {
              name
              kind
            }
          }
        }
      }
    }
    """
    res = run_graphql(query)
    fields = res.get("data", {}).get("__type", {}).get("fields", [])
    for f in fields:
        if f["name"] == "standardMetafieldDefinitionTemplates":
            print("standardMetafieldDefinitionTemplates arguments:")
            for arg in f["args"]:
                print(f" - {arg['name']} ({arg['type']['name']} / {arg['type']['kind']})")
            break

if __name__ == "__main__":
    main()
