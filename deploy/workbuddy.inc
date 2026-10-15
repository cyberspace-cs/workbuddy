# ============================================================
# WorkBuddy 多智能体 AI 助手（后端 9000，子路径 /workbuddy）
# 仅在 taoxie.vip 的 443 server 块内 include 本片段；不动根域名作品集与其他子路径。
# ============================================================
location = /workbuddy { return 301 /workbuddy/; }
location /workbuddy/ {
    proxy_pass http://127.0.0.1:9000/;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection        "";
    # SSE 流式（/workbuddy/api/chat）必须关闭代理缓冲
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout  3600s;
    proxy_send_timeout  3600s;
    chunked_transfer_encoding on;
    add_header X-Accel-Buffering no;
}
