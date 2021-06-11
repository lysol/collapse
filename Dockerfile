FROM ubuntu:latest
RUN apt-get update \
	&& apt-get install -y python3-pip \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*
COPY ./ /collapse
#COPY collapse.json /src/collapse.json
RUN cd /collapse && \
	pip3 install -r requirements.txt && \
	python3 setup.py install
CMD [ "python -m collapse" ]
