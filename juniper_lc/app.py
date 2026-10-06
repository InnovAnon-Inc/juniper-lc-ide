import os
import sys
from flask import Flask, request, jsonify, render_template, send_from_directory
from .lc import execute_program, GRAPHICS_STATE

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    # Resolves favicon.ico relative to the package root
    #root_dir = os.path.abspath(os.path.join(app.root_path, '..'))
    #return send_from_directory(root_dir, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    return send_from_directory(app.root_path, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/api/evaluate', methods=['POST'])
def evaluate():
    data = request.get_json() or {}
    code = data.get('code', '')

    # Reset recorded graphics primitives before each run
    GRAPHICS_STATE["papers"] = {}

    env = {}
    declared = {}

    try:
        output_lines, final_env, final_declared = execute_program(
            filename="<web_ide>",
            code=code,
            env=env,
            declared_terms=declared,
            quiet=True
        )

        return jsonify({
            "status": "success",
            "output": output_lines,
            "graphics": GRAPHICS_STATE["papers"],
            "declared_symbols": list(final_declared.keys())
        })

    except SystemExit:
        return jsonify({
            "status": "error",
            "message": "Evaluation or assertion failed during execution."
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == '__main__':
    print("🚀 Lambda Calculus IDE starting on http://localhost:5013")
    app.run(host='0.0.0.0', port=5013, debug=True)
