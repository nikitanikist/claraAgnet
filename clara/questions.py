"""Structured questions keep the decision readable and optional context available."""


def question_data(args):
    question=args.get('question','')
    if not isinstance(question,str) or not question.strip():
        raise ValueError('Ask one clear question.')
    result={'question':question.strip()}
    for key in ('context','details'):
        if args.get(key):
            if not isinstance(args[key],str): raise ValueError(key+' must be text.')
            result[key]=args[key].strip()
    choices=args.get('choices',[])
    if not isinstance(choices,list) or len(choices)>4: raise ValueError('Offer up to four choices.')
    if choices:
        if any(not isinstance(c,dict) or not isinstance(c.get('label'),str) or not c['label'].strip()
               or not isinstance(c.get('answer'),str) or not c['answer'].strip() for c in choices):
            raise ValueError('Each choice needs a short label and its full answer.')
        result['choices']=[{'label':c['label'].strip(),'answer':c['answer'].strip()} for c in choices]
    return result


QUESTION_SCHEMA={'type':'object','properties':{
    'question':{'type':'string','description':'One short, plain question, preferably under 180 characters. No status report or internal IDs.'},
    'context':{'type':'string','description':'One or two short sentences needed to decide. Keep consequences and meaningful differences visible.'},
    'details':{'type':'string','description':'Optional supporting details; displayed under Show details. Put logs, filenames, paths and lengthy explanations here.'},
    'choices':{'type':'array','maxItems':4,'items':{'type':'object','properties':{
        'label':{'type':'string','description':'Short button label, preferably 2–6 words.'},
        'answer':{'type':'string','description':'The complete answer submitted only if the user clicks this choice.'}},'required':['label','answer']}}
},'required':['question']}
