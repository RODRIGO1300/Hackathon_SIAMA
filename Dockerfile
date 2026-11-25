FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY siama_gaps ./siama_gaps
COPY api ./api
COPY web ./web
COPY datos ./datos
# Pipeline completo en la construcción: la imagen arranca con resultados listos.
# Para datos oficiales: reemplazar ./datos y reconstruir, o montar volúmenes y ejecutar
#   docker run ... python -m siama_gaps run --datos /datos --salida /app/salidas
RUN python -m siama_gaps run --datos datos --salida salidas
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
