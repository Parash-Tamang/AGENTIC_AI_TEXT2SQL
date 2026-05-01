class AppBaseException(Exception):
    """Base for all custom exceptions"""

    def __init__(self, message: str, code: str = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.code}] {self.message}" if self.code else self.message
