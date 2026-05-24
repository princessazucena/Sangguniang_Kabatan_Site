"""
Elastic Beanstalk entry point.

EB's Python platform looks for a module-level `application` callable
by default, so we expose it here. `python app.py` still works locally.
"""
from app import create_app

application = create_app()

if __name__ == "__main__":
    application.run()
