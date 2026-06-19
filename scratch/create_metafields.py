import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.shopify_graphql import run_graphql

def create_definition(key, name, type_name):
    mutation = """
    mutation CreateMetafieldDefinition($definition: MetafieldDefinitionInput!) {
      metafieldDefinitionCreate(definition: $definition) {
        createdDefinition {
          id
          key
          name
          namespace
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {
        "definition": {
            "namespace": "shopify",
            "key": key,
            "name": name,
            "ownerType": "PRODUCT",
            "type": type_name
        }
    }
    print(f"Creating definition for shopify.{key}...")
    res = run_graphql(mutation, variables)
    errors = res.get("data", {}).get("metafieldDefinitionCreate", {}).get("userErrors", [])
    if errors:
        print(f"  ❌ Errors: {errors}")
    else:
        created = res.get("data", {}).get("metafieldDefinitionCreate", {}).get("createdDefinition", {})
        print(f"  ✓ Created: {created.get('name')} ({created.get('id')})")

def main():
    # Attempt to create the 4 missing definitions
    create_definition("accessory-size", "Accessory size", "list.metaobject_reference")
    create_definition("bag-case-closure", "Bag/Case closure", "list.metaobject_reference")
    create_definition("bag-case-features", "Bag/Case features", "list.metaobject_reference")
    create_definition("bag-case-storage-features", "Bag/Case storage features", "list.metaobject_reference")

if __name__ == "__main__":
    main()
