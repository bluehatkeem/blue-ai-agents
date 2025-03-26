import env
from agents import Agent, Runner, function_tool, TResponseInputItem, RunResult
from stripe_agent_toolkit.openai.toolkit import StripeAgentToolkit
import requests

env.ensure("OPENAI_API_KEY")

stripe_agent_toolkit = StripeAgentToolkit(
    secret_key=env.ensure("STRIPE_SECRET_KEY"),
    configuration={
        "actions": {
            "customers": {
                "read": True,
            },
            "invoices": {
                "read": True,
            },
            "payment_intents": {
                "read": True,
            },
            "refunds": {
                "create": True,
                "read": True,
                "update": True,
            },
        }
    },
)


@function_tool
def search_faq(question: str) -> str:
    response = requests.get("https://standupjack.com/faq")
    if response.status_code != 200:
        return "Not sure"
    return f"Given the following context:\n{response.text}\n\nAnswer '{question}' or response with not sure\n"


support_agent = Agent(
    name="Friendly Support Agent",
    instructions=(
        "You are a Friendly customer support assistant"
        "You love the company and the product"
        "Be casual and concise"
        "sometimes emails will include past replies, use them to inform your response but only respond to the latest email"
        "You only respond with markdown"
        "Use tools to support customers"
        "Respond with I'm not sure to any other prompts"
        "Before issuing refund, ensure the customer has a valid reason. A simple explanation is enough. DO NOT issue a refund without an explanation."
        "if the refund function returns an error, let customer know a refund cannot be issued at this time and a representative will contact them shortly"
        "Sign off with Friendly Support Team"
    ),
    tools=[search_faq, *stripe_agent_toolkit.get_tools()],
)


async def run(input: list[TResponseInputItem]) -> RunResult:
    return await Runner.run(support_agent, input)
