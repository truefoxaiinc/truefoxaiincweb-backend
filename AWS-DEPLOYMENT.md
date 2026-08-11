# AWS backend and Vercel frontend deployment

## Recommended production layout

- Vercel hosts only the Next.js frontend.
- AWS Application Load Balancer terminates HTTPS for `api.truefoxaiinc.com`.
- ECS Fargate runs the FastAPI container from ECR on private subnets.
- An encrypted EFS access point is mounted at `/app/data` for the SQLite database and uploaded knowledge files.
- AWS Secrets Manager supplies `OPENAI_API_KEY`, `ADMIN_PASSWORD`, `ADMIN_SESSION_SECRET`, and `ADMIN_API_KEY`.
- CloudWatch receives container logs and alarms on failed health checks.

For multiple API replicas or high write volume, migrate persistence to Amazon RDS PostgreSQL before scaling past one task. The included SQLite configuration is deliberately single-writer and should run as exactly one ECS task with EFS backups.

## Backend environment

Set `APP_ENV=production`, `HOST=0.0.0.0`, `DATABASE_PATH=/app/data/truefox.sqlite3`, `FRONTEND_ORIGINS=https://your-project.vercel.app,https://truefoxaiinc.com`, the four secrets listed above, and the desired OpenAI models. Restrict the ALB security group to ports 80/443 and the ECS service security group to traffic from the ALB only.

Build and publish the Docker image to ECR, create the EFS mount, and deploy one ECS task on port 8000. Configure the ALB health check as `GET /health`. Enable automatic EFS backups and CloudWatch retention.

## Vercel environment

Set `NEXT_PUBLIC_API_URL=https://api.truefoxaiinc.com`. No database, admin password, OpenAI key, or backend secret belongs in Vercel. Redeploy after changing this public URL.

## DNS and TLS

Issue an ACM certificate for `api.truefoxaiinc.com`, attach it to the ALB HTTPS listener, and create a Route 53 alias record to the ALB. Keep HTTP redirected to HTTPS.
