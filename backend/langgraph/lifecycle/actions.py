"""
There are these actions

Cancel: apply to thread/node/task
Re-explore: only apply to node, which is exactly the langgraph fork in time travel
Resume: only apply to thread, which is just to recover from last time travel point, and continue to execute the rest of the graph.

"""