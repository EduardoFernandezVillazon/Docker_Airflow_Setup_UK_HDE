import requests
from pandas import DataFrame
from pandas import read_sql_query
from io import StringIO
from sqlalchemy import create_engine
from airflow.models import BaseOperator
from airflow.models import Variable
from airflow.utils.decorators import apply_defaults
from airflow.hooks.S3_hook import S3Hook
import fastparquet


class GetHydrologyAPIOperator(BaseOperator):
    ui_color = '#358140'

    template_fields = ['date']

    @apply_defaults
    def __init__(self,
                 postgres_conn_id="",
                 origin_database="airflow",
                 origin_table="stations",
                 origin_user="airflow",
                 origin_password="airflow",
                 origin_sql_connection="",
                 destination_database="airflow",
                 destination_table="measures",
                 destination_user="airflow",
                 destination_password="airflow",
                 destination_sql_connection="",
                 physical_quantity="waterFlow",
                 measures_df=DataFrame([]),
                 general_API_endpoint="https://environment.data.gov.uk/hydrology/data/readings.json?period={period}&station.stationReference={station_reference}&date={date}",
                 date="",
                 aws_conn_id='aws_credentials',
                 s3_key="",
                 *args, **kwargs):

        super(GetHydrologyAPIOperator, self).__init__(*args, **kwargs)
        self.postgres_conn_id = postgres_conn_id
        self.origin_database = origin_database
        self.origin_table = origin_table
        self.origin_user = origin_user
        self.origin_password = origin_password
        self.destination_database = destination_database
        self.destination_table = destination_table
        self.destination_user = destination_user
        self.destination_password = destination_password
        self.physical_quantity = physical_quantity
        self.date = date
        self.aws_conn_id = aws_conn_id
        self.s3_key = s3_key
        self.origin_sql_connection = origin_sql_connection
        self.destination_sql_connection = destination_sql_connection
        self.measures_df = measures_df
        self.general_API_endpoint = general_API_endpoint

    def create_connections(self):
        self.origin_sql_connection = create_engine(
            "postgresql+psycopg2://{user}:{password}@postgres:5432/{database}".format(user=self.origin_user,
                                                                                      password=self.origin_password,
                                                                                      database=self.origin_database
                                                                                      )
        )

        self.destination_sql_connection = create_engine(
            "postgresql+psycopg2://{user}:{password}@postgres:5432/{database}".format(user=self.destination_user,
                                                                                      password=self.destination_password,
                                                                                      database=self.destination_database
                                                                                      )
        )

    def save_locally(self, station_reference):
        try:
            self.measures_df.to_parquet(fname=str(self.date) + "/" + str(station_reference) + ".parquet",
                                   partition_cols=["date", "stationReference"])
        except Exception as e:
            self.log.info(print(e))
            self.log.info(print("Failure to save parquet file locally"))

    def read_json(self, station_reference):
        try:
            API_endpoint = self.general_API_endpoint.format(
                period=900, station_reference=station_reference, date=self.date
            )
            response = requests.get(API_endpoint)
            measures = response.json()["items"]
            self.measures_df = DataFrame.from_dict(measures)
        except Exception as e:
            self.log.info(print(e))
            self.log.info(print("Failure to read JSON from the API"))

    def process_dataframe(self, station_reference, lat, long):
        try:
            columns_to_drop = ["measure"]  # , "date"]
            # self.log.info(print(measures_df))
            self.measures_df.drop(columns=columns_to_drop, inplace=True)
            self.measures_df["stationReference"] = station_reference
            self.measures_df["lat"] = lat
            self.measures_df["long"] = long
            self.measures_df["physicalQuantity"] = self.physical_quantity
            self.measures_df.reset_index(drop=True, inplace=True)
        except Exception as e:
            self.log.info(print(e))
            self.log.info(print("Failure to process the dataframe"))

    def write_to_local_sql(self):
        try:
            self.measures_df.head(0).to_sql(name=self.destination_table, con=self.destination_sql_connection,
                                       if_exists='append', index=False)

            conn = self.destination_sql_connection.raw_connection()
            cur = conn.cursor()
            output = StringIO()
            self.measures_df.to_csv(output, sep='\t', header=False, index=False)
            output.seek(0)
            cur.copy_from(output, self.destination_table, null="", sep='\t')
            conn.commit()
        except Exception as e:
            self.log.info(print(e))
            self.log.info(print("Failure to write to local database"))

    def execute(self, context):

        self.create_connections()

        station_reference_df = read_sql_query(
            'SELECT label, "stationReference", lat, long FROM {table};'.format(
                table=self.origin_table), con=self.origin_sql_connection
        )

        for station_reference, lat, long in zip(station_reference_df["stationReference"], station_reference_df["lat"],
                                                station_reference_df["long"]):

            try:
                self.read_json(station_reference=station_reference)
                self.process_dataframe(station_reference=station_reference, lat=lat, long=long)
                self.write_to_local_sql()
                self.save_locally(station_reference)
            except:
                self.log.info(print("Station may not have this type of measure"))

            # try:
            #     hook = S3Hook(aws_conn_id=self.aws_conn_id)
            #     self.log.info(print(hook))
            #     credentials = hook.get_credentials()
            #     bucket = Variable.get('s3_bucket')
            #     self.log.info(print(bucket))
            #     rendered_key = self.s3_key.format(**context)
            #     s3_path="s3://{access}:{secret}@{bucket}/{rendered_key}".format(access=credentials.access_key, secret=credentials.secret_key, bucket=bucket, rendered_key=rendered_key)
            #     self.log.info(print(s3_path))
            #
            #     #  .to_csv(s3_path+str(self.date)+str(station_reference)+".csv")
            # except Exception as e:
            #     self.log.info(print(e))