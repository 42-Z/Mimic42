export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  graphql_public: {
    Tables: {
      [_ in never]: never
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      graphql: {
        Args: {
          extensions?: Json
          operationName?: string
          query?: string
          variables?: Json
        }
        Returns: Json
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
  public: {
    Tables: {
      agent_events: {
        Row: {
          actor_user_id: string | null
          agent_id: string
          completed_at: string | null
          created_at: string
          error: string | null
          event_type: string
          id: string
          payload: Json
          result: Json | null
          started_at: string | null
          status: Database["public"]["Enums"]["agent_event_status"]
        }
        Insert: {
          actor_user_id?: string | null
          agent_id: string
          completed_at?: string | null
          created_at?: string
          error?: string | null
          event_type: string
          id?: string
          payload?: Json
          result?: Json | null
          started_at?: string | null
          status?: Database["public"]["Enums"]["agent_event_status"]
        }
        Update: {
          actor_user_id?: string | null
          agent_id?: string
          completed_at?: string | null
          created_at?: string
          error?: string | null
          event_type?: string
          id?: string
          payload?: Json
          result?: Json | null
          started_at?: string | null
          status?: Database["public"]["Enums"]["agent_event_status"]
        }
        Relationships: [
          {
            foreignKeyName: "agent_events_actor_user_id_fkey"
            columns: ["actor_user_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "agent_events_agent_id_fkey"
            columns: ["agent_id"]
            isOneToOne: false
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
        ]
      }
      agent_messages: {
        Row: {
          agent_id: string
          content: string
          created_at: string
          direction: Database["public"]["Enums"]["agent_message_direction"]
          id: string
          payload: Json
          role: string
          telegram_message_id: string | null
          thread_id: string | null
        }
        Insert: {
          agent_id: string
          content: string
          created_at?: string
          direction: Database["public"]["Enums"]["agent_message_direction"]
          id?: string
          payload?: Json
          role: string
          telegram_message_id?: string | null
          thread_id?: string | null
        }
        Update: {
          agent_id?: string
          content?: string
          created_at?: string
          direction?: Database["public"]["Enums"]["agent_message_direction"]
          id?: string
          payload?: Json
          role?: string
          telegram_message_id?: string | null
          thread_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "agent_messages_agent_id_fkey"
            columns: ["agent_id"]
            isOneToOne: false
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "agent_messages_thread_id_fkey"
            columns: ["thread_id"]
            isOneToOne: false
            referencedRelation: "message_threads"
            referencedColumns: ["id"]
          },
        ]
      }
      agent_onboarding_sessions: {
        Row: {
          agent_name: string | null
          api_hash_ciphertext: string | null
          api_id: number | null
          authorization_status: Database["public"]["Enums"]["telegram_authorization_status"]
          completed_agent_id: string | null
          created_at: string
          id: string
          last_error: string | null
          owner_id: string
          phone_code_hash_ciphertext: string | null
          phone_number: string | null
          session_ciphertext: string | null
          soul_prompt: string | null
          updated_at: string
        }
        Insert: {
          agent_name?: string | null
          api_hash_ciphertext?: string | null
          api_id?: number | null
          authorization_status?: Database["public"]["Enums"]["telegram_authorization_status"]
          completed_agent_id?: string | null
          created_at?: string
          id?: string
          last_error?: string | null
          owner_id: string
          phone_code_hash_ciphertext?: string | null
          phone_number?: string | null
          session_ciphertext?: string | null
          soul_prompt?: string | null
          updated_at?: string
        }
        Update: {
          agent_name?: string | null
          api_hash_ciphertext?: string | null
          api_id?: number | null
          authorization_status?: Database["public"]["Enums"]["telegram_authorization_status"]
          completed_agent_id?: string | null
          created_at?: string
          id?: string
          last_error?: string | null
          owner_id?: string
          phone_code_hash_ciphertext?: string | null
          phone_number?: string | null
          session_ciphertext?: string | null
          soul_prompt?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_onboarding_sessions_completed_agent_id_fkey"
            columns: ["completed_agent_id"]
            isOneToOne: true
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "agent_onboarding_sessions_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      agent_timers: {
        Row: {
          agent_id: string
          created_at: string
          description: string
          id: string
          peer: string
          status: string
          trigger_at: string
        }
        Insert: {
          agent_id: string
          created_at?: string
          description: string
          id?: string
          peer: string
          status?: string
          trigger_at: string
        }
        Update: {
          agent_id?: string
          created_at?: string
          description?: string
          id?: string
          peer?: string
          status?: string
          trigger_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "agent_timers_agent_id_fkey"
            columns: ["agent_id"]
            isOneToOne: false
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
        ]
      }
      agents: {
        Row: {
          created_at: string
          id: string
          last_started_at: string | null
          last_stopped_at: string | null
          name: string
          owner_id: string
          settings: Json
          soul_prompt: string
          status: Database["public"]["Enums"]["agent_runtime_status"]
          updated_at: string
        }
        Insert: {
          created_at?: string
          id?: string
          last_started_at?: string | null
          last_stopped_at?: string | null
          name: string
          owner_id: string
          settings?: Json
          soul_prompt?: string
          status?: Database["public"]["Enums"]["agent_runtime_status"]
          updated_at?: string
        }
        Update: {
          created_at?: string
          id?: string
          last_started_at?: string | null
          last_stopped_at?: string | null
          name?: string
          owner_id?: string
          settings?: Json
          soul_prompt?: string
          status?: Database["public"]["Enums"]["agent_runtime_status"]
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "agents_owner_id_fkey"
            columns: ["owner_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      message_threads: {
        Row: {
          agent_id: string
          created_at: string
          id: string
          last_message_at: string | null
          metadata: Json
          telegram_peer_id: string
          title: string | null
          updated_at: string
        }
        Insert: {
          agent_id: string
          created_at?: string
          id?: string
          last_message_at?: string | null
          metadata?: Json
          telegram_peer_id: string
          title?: string | null
          updated_at?: string
        }
        Update: {
          agent_id?: string
          created_at?: string
          id?: string
          last_message_at?: string | null
          metadata?: Json
          telegram_peer_id?: string
          title?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "message_threads_agent_id_fkey"
            columns: ["agent_id"]
            isOneToOne: false
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          created_at: string
          display_name: string | null
          email: string | null
          id: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          display_name?: string | null
          email?: string | null
          id: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          display_name?: string | null
          email?: string | null
          id?: string
          updated_at?: string
        }
        Relationships: []
      }
      telegram_sessions: {
        Row: {
          agent_id: string
          api_hash_ciphertext: string | null
          api_id: number | null
          authorization_status: Database["public"]["Enums"]["telegram_authorization_status"]
          created_at: string
          id: string
          last_authorized_at: string | null
          last_error: string | null
          phone_number: string | null
          session_ciphertext: string | null
          session_name: string
          updated_at: string
        }
        Insert: {
          agent_id: string
          api_hash_ciphertext?: string | null
          api_id?: number | null
          authorization_status?: Database["public"]["Enums"]["telegram_authorization_status"]
          created_at?: string
          id?: string
          last_authorized_at?: string | null
          last_error?: string | null
          phone_number?: string | null
          session_ciphertext?: string | null
          session_name: string
          updated_at?: string
        }
        Update: {
          agent_id?: string
          api_hash_ciphertext?: string | null
          api_id?: number | null
          authorization_status?: Database["public"]["Enums"]["telegram_authorization_status"]
          created_at?: string
          id?: string
          last_authorized_at?: string | null
          last_error?: string | null
          phone_number?: string | null
          session_ciphertext?: string | null
          session_name?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "telegram_sessions_agent_id_fkey"
            columns: ["agent_id"]
            isOneToOne: true
            referencedRelation: "agents"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      agent_event_status:
        | "pending"
        | "running"
        | "succeeded"
        | "failed"
        | "cancelled"
      agent_message_direction:
        | "incoming"
        | "outgoing"
        | "dashboard_trigger"
        | "agent_response"
        | "tool_call"
        | "tool_result"
      agent_runtime_status:
        | "draft"
        | "stopped"
        | "starting"
        | "running"
        | "stopping"
        | "error"
      telegram_authorization_status:
        | "not_started"
        | "code_requested"
        | "password_required"
        | "authorized"
        | "revoked"
        | "error"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  graphql_public: {
    Enums: {},
  },
  public: {
    Enums: {
      agent_event_status: [
        "pending",
        "running",
        "succeeded",
        "failed",
        "cancelled",
      ],
      agent_message_direction: [
        "incoming",
        "outgoing",
        "dashboard_trigger",
        "agent_response",
        "tool_call",
        "tool_result",
      ],
      agent_runtime_status: [
        "draft",
        "stopped",
        "starting",
        "running",
        "stopping",
        "error",
      ],
      telegram_authorization_status: [
        "not_started",
        "code_requested",
        "password_required",
        "authorized",
        "revoked",
        "error",
      ],
    },
  },
} as const
