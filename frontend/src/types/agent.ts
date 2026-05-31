/** Agent capability types aligned to backend fin_agents.agent_skills and task memory. */

export interface ToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface TaskMemory {
  task_id: string;
  node_id: string;
  node_name: string;
  task_name: string;
  description: string;
  status: string;
  output?: Record<string, unknown> | null;
  updated_at?: string | null;
}

export type SkillStatus = 'active' | 'forgotten';

export interface Skill {
  skill_id: string;
  thread_id: string;
  node_id: string;
  summary: string;
  instructions: string;
  status: SkillStatus;
  created_at: string;
}

export interface AgentCapabilities {
  tools: ToolInfo[];
  skills: Skill[];
  memory: TaskMemory[];
}

export interface NodeSkillFile {
  filename: string;
  content: string;
}

export interface NodeSkillsResponse {
  node_name: string;
  skills: NodeSkillFile[];
}
