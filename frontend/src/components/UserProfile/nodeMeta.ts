/**
 * Static metadata for every graph node that has user-configurable options.
 * This drives the UserProfile preference UI without hardcoding any UI element.
 *
 * node_name "__global__" represents settings that apply graph-wide.
 */

import type { NodeConfig } from '../../types';

export interface NodeConfigField {
  key: keyof NodeConfig;
  label: string;
  type: 'boolean' | 'select' | 'number';
  /** Options for type === 'select' */
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  description: string;
}

export interface NodeMeta {
  node_name: string;
  display_name: string;
  category: 'Global' | 'Query' | 'Regional' | 'Research' | 'Analysis' | 'Synthesis';
  fields: NodeConfigField[];
}

export const NODE_METAS: NodeMeta[] = [
  {
    node_name: '__global__',
    display_name: 'Global (all nodes)',
    category: 'Global',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Human-in-the-loop (default)',
        type: 'boolean',
        description: 'Default review gate applied to all nodes unless overridden per-node.',
      },
    ],
  },
  {
    node_name: 'query_node',
    display_name: 'Query Node',
    category: 'Query',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review before routing',
        type: 'boolean',
        description: 'Pause after query parsing and wait for your approval before the graph routes to a regional node.',
      },
    ],
  },
  {
    node_name: 'apac_analyze_node',
    display_name: 'APAC Analyze Node',
    category: 'Regional',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review regional analysis',
        type: 'boolean',
        description: 'Pause after APAC market analysis and wait for approval.',
      },
      {
        key: 'depth',
        label: 'Analysis depth',
        type: 'select',
        options: [
          { value: 'shallow', label: 'Shallow — fast overview' },
          { value: 'normal', label: 'Normal — balanced' },
          { value: 'deep', label: 'Deep — thorough' },
        ],
        description: 'Controls how many data sources and reasoning steps are used.',
      },
    ],
  },
  {
    node_name: 'emea_analyze_node',
    display_name: 'EMEA Analyze Node',
    category: 'Regional',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review regional analysis',
        type: 'boolean',
        description: 'Pause after EMEA market analysis and wait for approval.',
      },
      {
        key: 'depth',
        label: 'Analysis depth',
        type: 'select',
        options: [
          { value: 'shallow', label: 'Shallow — fast overview' },
          { value: 'normal', label: 'Normal — balanced' },
          { value: 'deep', label: 'Deep — thorough' },
        ],
        description: 'Controls how many data sources and reasoning steps are used.',
      },
    ],
  },
  {
    node_name: 'amer_analyze_node',
    display_name: 'AMER Analyze Node',
    category: 'Regional',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review regional analysis',
        type: 'boolean',
        description: 'Pause after AMER market analysis and wait for approval.',
      },
      {
        key: 'depth',
        label: 'Analysis depth',
        type: 'select',
        options: [
          { value: 'shallow', label: 'Shallow — fast overview' },
          { value: 'normal', label: 'Normal — balanced' },
          { value: 'deep', label: 'Deep — thorough' },
        ],
        description: 'Controls how many data sources and reasoning steps are used.',
      },
    ],
  },
  {
    node_name: 'research_subgraph',
    display_name: 'Research Subgraph',
    category: 'Research',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review research plan',
        type: 'boolean',
        description: 'Pause before the research subgraph dispatches parallel tasks.',
      },
      {
        key: 'depth',
        label: 'Research depth',
        type: 'select',
        options: [
          { value: 'shallow', label: 'Shallow — quick facts' },
          { value: 'normal', label: 'Normal — standard research' },
          { value: 'deep', label: 'Deep — exhaustive search' },
        ],
        description: 'Controls number of sources fetched and agent iterations.',
      },
      {
        key: 'max_iterations',
        label: 'Max agent iterations',
        type: 'number',
        min: 1,
        max: 10,
        step: 1,
        description: 'Maximum number of deep-agent loop iterations for the research subgraph.',
      },
    ],
  },
  {
    node_name: 'analyze_stats_node',
    display_name: 'Analyze Stats Node',
    category: 'Analysis',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review stats analysis',
        type: 'boolean',
        description: 'Pause after quantitative stats analysis and wait for approval.',
      },
      {
        key: 'depth',
        label: 'Analysis depth',
        type: 'select',
        options: [
          { value: 'shallow', label: 'Shallow' },
          { value: 'normal', label: 'Normal' },
          { value: 'deep', label: 'Deep' },
        ],
        description: 'Controls number of statistical indicators computed.',
      },
    ],
  },
  {
    node_name: 'analyze_news_node',
    display_name: 'Analyze News Node',
    category: 'Analysis',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review news analysis',
        type: 'boolean',
        description: 'Pause after news sentiment analysis and wait for approval.',
      },
      {
        key: 'depth',
        label: 'Analysis depth',
        type: 'select',
        options: [
          { value: 'shallow', label: 'Shallow — headlines only' },
          { value: 'normal', label: 'Normal — article summaries' },
          { value: 'deep', label: 'Deep — full article analysis' },
        ],
        description: 'Controls how deeply news articles are processed.',
      },
    ],
  },
  {
    node_name: 'conclusion_node',
    display_name: 'Conclusion Node',
    category: 'Synthesis',
    fields: [
      {
        key: 'human_in_the_loop',
        label: 'Review before finalising',
        type: 'boolean',
        description: 'Pause after the conclusion draft and wait for your approval before streaming the final answer.',
      },
      {
        key: 'temperature',
        label: 'LLM temperature',
        type: 'number',
        min: 0,
        max: 2,
        step: 0.1,
        description: 'Sampling temperature for the conclusion LLM (0 = deterministic, 2 = very creative).',
      },
      {
        key: 'detail_level',
        label: 'Output detail level',
        type: 'select',
        options: [
          { value: 'brief', label: 'Brief — executive summary' },
          { value: 'standard', label: 'Standard — balanced report' },
          { value: 'detailed', label: 'Detailed — full analysis' },
        ],
        description: 'Controls the length and depth of the final conclusion.',
      },
    ],
  },
];
