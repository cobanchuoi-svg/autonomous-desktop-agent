"""
GUI launcher entry point.
"""

from agent.ui.dashboard import AgentDashboard


def main():
    dashboard = AgentDashboard()
    dashboard.run()


if __name__ == "__main__":
    main()
