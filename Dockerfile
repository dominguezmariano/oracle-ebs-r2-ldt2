FROM python:3.12-slim

# Oracle Instant Client 21.12 (thick mode â soporta verifiers 10g/11g/12c)
# libaio1t64: nombre en Debian Trixie; se crea symlink libaio.so.1 para compatibilidad
RUN apt-get update && apt-get install -y --no-install-recommends \
        libaio1t64 wget unzip ca-certificates && \
    ln -s /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 && \
    wget -q https://download.oracle.com/otn_software/linux/instantclient/2112000/instantclient-basiclite-linux.x64-21.12.0.0.0dbru.zip \
        -O /tmp/ic.zip && \
    unzip -q /tmp/ic.zip -d /opt/oracle && \
    rm /tmp/ic.zip && \
    echo /opt/oracle/instantclient_21_12 > /etc/ld.so.conf.d/oracle-instantclient.conf && \
    ldconfig && \
    apt-get remove -y wget unzip && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_21_12

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "run:app"]
