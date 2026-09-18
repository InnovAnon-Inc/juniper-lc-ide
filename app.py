from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    with open('index.html', 'r', encoding='utf-8') as f:
        return f.read()

if __name__ == '__main__':
    print("🚀 Lambda Calculus IDE starting on http://localhost:5013")
    app.run(host='0.0.0.0', port=5013, debug=True)
