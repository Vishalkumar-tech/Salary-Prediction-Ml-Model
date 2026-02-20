import pandas as pd
from sklearn.linear_model import LinearRegression
import pickle
data = pd.read_csv("../data/salary_data.csv")
X = data[['experience', 'age']]
y = data['salary']
model = LinearRegression()
model.fit(X, y)
with open("../model.pkl", "wb") as f:
    pickle.dump(model, f)

print("Model trained and saved successfully")