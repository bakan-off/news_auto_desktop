"""Обеспечивает доступ к модулям проекта из тестов (запуск из корня репозитория)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
