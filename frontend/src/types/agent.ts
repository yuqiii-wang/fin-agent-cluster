/** Agent capability types aligned to backend fin_agents.agent_skills / agent_memory. */

export interface ToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export type MemoryEntryType =
  | 'task_result'
  | 'tool_call'
  | 'skill_applied'
  | 'reasoning'
  | 'compacted_summary';

export type MemoryStatus = 'active' | 'forgotten' | 'compacted';

export interface MemoryEntry {
  memory_id: string;
  thread_id: string;
  node_id: string;
  entry_type: MemoryEntryType;
  content: Record<string, unknown>;
  seq_num: number;
  status: MemoryStatus;
  compacted_into?: string | null;
  created_at: string;
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
  memory: MemoryEntry[];
}

export interface StepStateEntry {
  node_id: string;
  iteration: number;
  global_state: Record<string, unknown>;
  step_state: Record<string, unknown>;
  updated_at: string;
}

export interface AgentStepStatesResponse {
  iterations: StepStateEntry[];
}

export interface NodeSkillFile {
  filename: string;
  content: string;
}

export interface NodeSkillsResponse {
  node_name: string;
  skills: NodeSkillFile[];
}
