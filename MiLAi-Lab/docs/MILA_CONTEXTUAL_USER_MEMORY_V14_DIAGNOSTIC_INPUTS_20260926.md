# v14 V1 公开输入规范

这里只包含允许进入 Host 的自建虚构输入和本地工具定义。不是 MERIT 数据或成绩。

2026-09-26 在实现与窄检查后冻结，共 12 个实例、20 个声明会话。实际 JSON 的 SHA-256 为 `a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc`。首批 d01/d05/d12，源码与配置身份见 [冻结清单](../data/manifests/contextual-memory-v14-diagnostic-freeze.json)。所有任务、人物、代号及工具世界均为人工构造，无真实用户数据。

下列唯一 JSON 块是可复现的精确规范；提取块内文本（保留末尾换行）即可得到对应 `inputs.json`。输入与评分规范始终分别保存。

```json
{
  "kind": "INDEPENDENT_SYNTHETIC_SEMANTIC_DIAGNOSTIC",
  "version": "v14-v1-1",
  "initialization": "Each case starts with an empty bank and its declared local fixture tools; actions affect only the controlled fixture call log.",
  "cases": [
    {
      "id": "d01",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For this reply only, calculate 135 times 4 and return just the number. This formatting instruction is only for this calculation."
            }
          ]
        }
      ]
    },
    {
      "id": "d02",
      "tools": [
        {
          "schema": {
            "type": "function",
            "function": {
              "name": "message_courier",
              "description": "Send a message to the courier desk. A delivery receipt proves message delivery only.",
              "parameters": {
                "type": "object",
                "properties": {
                  "parcel_id": {
                    "type": "string"
                  },
                  "message": {
                    "type": "string"
                  }
                },
                "required": [
                  "parcel_id",
                  "message"
                ],
                "additionalProperties": false
              }
            }
          },
          "result": {
            "status": "succeeded",
            "output": {
              "message_id": "MSG-K17",
              "delivered": true,
              "parcel_id": "K17"
            }
          }
        },
        {
          "schema": {
            "type": "function",
            "function": {
              "name": "release_parcel",
              "description": "Release the named parcel for collection.",
              "parameters": {
                "type": "object",
                "properties": {
                  "parcel_id": {
                    "type": "string"
                  }
                },
                "required": [
                  "parcel_id"
                ],
                "additionalProperties": false
              }
            }
          },
          "result": {
            "status": "succeeded",
            "output": {
              "released": true,
              "parcel_id": "K17"
            }
          }
        }
      ],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "Send the courier desk a message for parcel K17: hold it at bay 6 until I confirm pickup. Keep the dispatch receipt available for our next conversation. Do not release the parcel."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "What message did we send about my parcel, and what was its dispatch receipt? Do not release it."
            }
          ]
        }
      ]
    },
    {
      "id": "d03",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "From now on, use ISO date format YYYY-MM-DD in project summaries for me. Confirm today's date 2026-09-26 in that format."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "Which date format should you use in my project summaries?"
            }
          ]
        }
      ]
    },
    {
      "id": "d04",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For this reply only, explain why we check battery levels first, then put READY at the very end. Do not carry this ordering to later tasks."
            }
          ]
        }
      ]
    },
    {
      "id": "d05",
      "tools": [
        {
          "schema": {
            "type": "function",
            "function": {
              "name": "send_agenda",
              "description": "Send an agenda to the named workshop.",
              "parameters": {
                "type": "object",
                "properties": {
                  "workshop": {
                    "type": "string"
                  },
                  "agenda": {
                    "type": "string"
                  }
                },
                "required": [
                  "workshop",
                  "agenda"
                ],
                "additionalProperties": false
              }
            }
          },
          "result": {
            "status": "succeeded",
            "output": {
              "sent": true,
              "workshop": "Cedar"
            }
          }
        }
      ],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "Tomorrow, when I ask you to prepare the agenda for the Cedar workshop, include a ten-minute accessibility review before the demo. Do not draft or send the agenda today."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "What is the outstanding agenda requirement for Cedar? Do not draft or send it yet."
            }
          ]
        }
      ]
    },
    {
      "id": "d06",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "Starting 2026-10-01, use kilograms instead of pounds in all my equipment inventory reports. Until then keep pounds. This is an ongoing reporting rule."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "On 2026-09-30 and 2026-10-02, what mass units should my equipment inventory reports use?"
            }
          ]
        }
      ]
    },
    {
      "id": "d07",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For this one answer, if 18 is even reply EVEN, otherwise ODD. This branch rule is only for this calculation."
            }
          ]
        }
      ]
    },
    {
      "id": "d08",
      "tools": [
        {
          "schema": {
            "type": "function",
            "function": {
              "name": "book_pickup",
              "description": "Book a pickup for the specified request, desk and time.",
              "parameters": {
                "type": "object",
                "properties": {
                  "request": {
                    "type": "string"
                  },
                  "desk": {
                    "type": "string"
                  },
                  "time": {
                    "type": "string"
                  }
                },
                "required": [
                  "request",
                  "desk",
                  "time"
                ],
                "additionalProperties": false
              }
            }
          },
          "result": {
            "status": "succeeded",
            "output": {
              "booked": true,
              "booking_id": "P-J18"
            }
          }
        }
      ],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For the Juniper loan request, book the pickup only after I explicitly say documents accepted. The pickup is at East Desk at 16:30. I have not accepted the documents. Keep this outstanding arrangement for our next conversation."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "What pickup is waiting for my decision? Do not book it."
            }
          ]
        }
      ]
    },
    {
      "id": "d09",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For every future remote interview, if a candidate is in a different time zone, send both my local time (Asia/Shanghai) and the candidate's local time; for same-zone interviews use just my local time. This applies across projects."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "What time information should I give a candidate in another time zone, and one in my own?"
            }
          ]
        }
      ]
    },
    {
      "id": "d10",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For this one response, note that the trial room is F-28. Do not store the room number or this instruction. Acknowledge briefly."
            }
          ]
        }
      ]
    },
    {
      "id": "d11",
      "tools": [
        {
          "schema": {
            "type": "function",
            "function": {
              "name": "contact_person",
              "description": "Send a message to the named person.",
              "parameters": {
                "type": "object",
                "properties": {
                  "person": {
                    "type": "string"
                  },
                  "message": {
                    "type": "string"
                  }
                },
                "required": [
                  "person",
                  "message"
                ],
                "additionalProperties": false
              }
            }
          },
          "result": {
            "status": "succeeded",
            "output": {
              "delivered": true,
              "message_id": "M-A19"
            }
          }
        }
      ],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "Answer this turn with one bullet. At our next Atlas planning session, remind me to ask Nina for the load-test log before choosing a deployment date. Do not contact Nina now."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "What should I do before choosing the Atlas deployment date?"
            }
          ]
        }
      ]
    },
    {
      "id": "d12",
      "tools": [],
      "sessions": [
        {
          "id": "s1",
          "turns": [
            {
              "id": "t1",
              "text": "For future repairs, remember that my desk microphone is model m0, written exactly in lower case. The spare connector is for that same m0 model."
            }
          ]
        },
        {
          "id": "s2",
          "turns": [
            {
              "id": "t1",
              "text": "Which microphone model and spare connector do I use?"
            }
          ]
        }
      ]
    }
  ]
}
```
