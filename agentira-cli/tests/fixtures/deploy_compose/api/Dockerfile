FROM python:3.11-alpine
WORKDIR /srv
RUN echo "api says hello" > index.html
CMD ["python3", "-m", "http.server", "9000"]
