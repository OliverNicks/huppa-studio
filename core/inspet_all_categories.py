import pandas as pd

df = pd.read_excel(r'data\huppa.xlsx')
df.copy()

all_colors = df['цвет'].dropna().drop_duplicates()
all_sizes = df['Артикул'].dropna().drop_duplicates().str.rsplit("-").str[2].drop_duplicates()
# print(all_colors)
print(all_sizes)
print(len(all_sizes))