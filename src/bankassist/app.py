"""Wires the bank, the message bus, the tracer and the four agents together."""

from __future__ import annotations

from .agents import AccountAgent, AuthAgent, ConciergeAgent, MessageBus, RiskAgent
from .bank import Bank
from .llm import llm_config
from .trace import Tracer


class BankAssistApp:
    def __init__(self, tracer: Tracer | None = None, bank: Bank | None = None):
        self.tracer = tracer or Tracer()
        self.bank = bank or Bank()
        self.bus = MessageBus(self.tracer)
        self.concierge = ConciergeAgent(self.bus, self.bank, self.tracer)
        self.auth = AuthAgent(self.bus, self.bank, self.tracer)
        self.account = AccountAgent(self.bus, self.bank, self.tracer)
        self.risk = RiskAgent(self.bus, self.bank, self.tracer)
        cfg = llm_config()
        self.tracer.meta["concierge_mode"] = f"llm ({cfg['model']})" if cfg else "rules"

    def new_conversation(self) -> None:
        """Forget the logged-in customer (as if a new chat window was opened)."""
        self.concierge.cancel_pending()
        self.concierge.session_token = None
        self.concierge.customer_id = None
        self.concierge.pending_ref = None

    def chat(self, customer_id: str, pin: str, text: str) -> str:
        return self.concierge.handle_user(customer_id, pin, text)
