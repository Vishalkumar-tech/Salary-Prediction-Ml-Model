# Salary Prediction using Linear Regression (ML + Flask)

Project Overview
I built a small Machine Learning project using Linear Regression to predict salary based on a person's age and experience.
This project uses:
Python
HTML
Flask
scikit-learn
Machine Learning (Linear Regression)
The goal of this project is to understand how Machine Learning models learn from existing data and predict outcomes for new inputs.

Understanding Linear Regression (My Learning)
Linear Regression is a statistical method used to predict an outcome based on dependent and independent variables.
The dependent variable (Y) is the output we want to predict.
The independent variables (X) are the inputs used to make the prediction.
There can be multiple independent variables.
The main goal of Linear Regression is to:
Find the coefficients (weights)
Find the slope of the data
Draw the best fit line

This best fit line represents the relationship between input variables and output.
Using this line, the model can predict outcomes for new data based on the pattern learned from previous data.
Variables used in this project
Independent variables (X):
Age
Experience
Dependent variable (Y):
Salary
The model learns the relationship between: Age + Experience → Salary and predicts salary based on these inputs.

How the model works

1. Load the dataset
2. Train the Linear Regression model using scikit-learn
3. The model finds the best coefficients and intercept
4. Save the trained model using pickle
5. Use Flask to create a web interface
6. User enters age and experience
7. Model predicts salary using learned relationship

Technologies Used
Python
scikit-learn
Flask
HTML
Pandas
NumPy
Pickle
