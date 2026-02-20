from flask import Flask, render_template, request
import pickle
import numpy as np
app = Flask(__name__)
model = pickle.load(open("model.pkl", "rb"))
@app.route("/", methods=["GET", "POST"])
def index():
    prediction = None
    if request.method == "POST":
        experience = float(request.form["experience"])
        age = float(request.form["age"])
        prediction = model.predict([[experience, age]])[0]
    return render_template("index.html", prediction=prediction)
if __name__ == "__main__":
    app.run(debug=True)