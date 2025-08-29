import pandas as pd

# Read the Excel file
df = pd.read_excel('madison_docs/DuProcess Indexes/2002-03-16.xlsx')

# Display columns
print('Columns:', df.columns.tolist())

# Display first 20 rows of InstrumentType column
print('\nFirst 20 rows of InstrumentType column:')
for i, val in enumerate(df['InstrumentType'].head(20)):
    print(f'{i+1}: {val}')

# Check for unique instrument types
print('\nUnique InstrumentType patterns (first part before " -"):')
unique_types = set()
for val in df['InstrumentType'].dropna():
    if ' -' in str(val):
        doc_type = str(val).split(' -')[0].strip()
        unique_types.add(doc_type)

for doc_type in sorted(unique_types):
    print(f'  {doc_type}')