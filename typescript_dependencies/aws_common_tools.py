import re
def remove_variable(arn:str):
    """
    transforms foo${lala}hello -> foohello
    :param arn:
    :return: str
    """
    return re.sub('\${.*}','', arn)

def arn2name4s3(arn:str):
    return remove_variable(arn).split(":")[-1].split("/")[0]

def arn2name4lambda(arn:str):
    return remove_variable(arn).split(':function:')[-1].split(':')[0]

def arn2name4sns(arn:str):
    return remove_variable(arn).split(":")[-1]

def arn2name4sqs(arn:str):
    return remove_variable(arn).split(":")[-1]

def url2name4sqs(url:str):
    return remove_variable(url).split("/")[-1]

def arn_or_url2name4sqs(arn:str):
    return url2name4sqs(arn2name4sqs(arn))