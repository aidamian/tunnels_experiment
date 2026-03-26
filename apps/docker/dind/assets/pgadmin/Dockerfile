FROM dpage/pgadmin4:latest

USER root
RUN python3 -m pip install --no-cache-dir "psycopg[binary]>=3.2,<4.0"
USER pgadmin
