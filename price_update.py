# Price update script for Meeeshop inventory
# This script contains the core logic to update product prices.
# It can be invoked manually or via a CI workflow.

def update_prices(data_source, price_rules):
    """Update prices based on provided rules.

    Args:
        data_source (Callable): Function that returns a list of product dicts.
        price_rules (Callable): Function that takes a product dict and returns a new price.
    """
    products = data_source()
    updated = []
    for product in products:
        new_price = price_rules(product)
        product['price'] = new_price
        updated.append(product)
    return updated

if __name__ == "__main__":
    # Example usage placeholder
    def dummy_source():
        return [{"id": 1, "price": 10}, {"id": 2, "price": 20}]

    def dummy_rules(product):
        # Simple rule: increase price by 10%
        return round(product["price"] * 1.10, 2)

    result = update_prices(dummy_source, dummy_rules)
    print("Updated products:", result)