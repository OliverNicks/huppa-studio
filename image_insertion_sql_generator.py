import os
import pandas as pd

def generate_image_sync_sql(excel_path: str, local_images_dir: str, output_sql_path: str = "update_images.sql"):
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Catalog file not found: {excel_path}")
    if not os.path.exists(local_images_dir):
        raise FileNotFoundError(f"Image directory not found: {local_images_dir}")

    # 1. Read catalog and disk images
    print("Reading catalog data...")
    df = pd.read_excel(excel_path) if excel_path.endswith(('.xlsx', '.xls')) else pd.read_csv(excel_path)
    existing_files = set(os.listdir(local_images_dir))

    # 2. Extract unique parent SKUs (e.g., 21700010-00009-00L -> 21700010-00009)
    unique_parents = (
        df['Артикул']
        .dropna()
        .astype(str)
        .apply(lambda x: '-'.join(x.strip().split('-')[:2]))
        .unique()
    )

    sql_statements = [
        "-- OpenCart Image Sync & Repair Script",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';\n"
    ]

    matched_parents = 0

    # 3. Build SQL statements
    for parent_id in unique_parents:
        main_img = f"{parent_id}_0.jpg"
        if main_img not in existing_files:
            continue

        matched_parents += 1

        # Cover photo
        sql_statements.append(
            f"UPDATE oc_product SET image = 'catalog/product/{main_img}' "
            f"WHERE sku LIKE '{parent_id}%' OR model LIKE '{parent_id}%';"
        )

        # Gallery photos
        gallery_images = []
        angle_idx = 1
        while f"{parent_id}_{angle_idx}.jpg" in existing_files:
            gallery_images.append((f"catalog/product/{parent_id}_{angle_idx}.jpg", angle_idx))
            angle_idx += 1

        if gallery_images:
            sql_statements.append(
                f"DELETE pi FROM oc_product_image pi "
                f"INNER JOIN oc_product p ON pi.product_id = p.product_id "
                f"WHERE p.sku LIKE '{parent_id}%' OR p.model LIKE '{parent_id}%';"
            )
            for img_path, sort_order in gallery_images:
                sql_statements.append(
                    f"INSERT INTO oc_product_image (product_id, image, sort_order) "
                    f"SELECT product_id, '{img_path}', {sort_order} "
                    f"FROM oc_product WHERE sku LIKE '{parent_id}%' OR model LIKE '{parent_id}%';"
                )

    sql_statements.append("\nSET FOREIGN_KEY_CHECKS = 1;")

    # 4. Save to disk
    with open(output_sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sql_statements))

    print(f"Done! Created '{output_sql_path}'.")
    print(f"Total parent products matched with local images: {matched_parents}/{len(unique_parents)}")

if __name__ == "__main__":
    # Adjust paths if your file names differ
    generate_image_sync_sql(
        excel_path=r"data\huppa.xlsx", 
        local_images_dir="opencart_images", 
        output_sql_path=r"output\update_images.sql"
    )