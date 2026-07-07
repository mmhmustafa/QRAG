type ValidationItem={loc?:unknown;msg?:unknown;type?:unknown};

function location(value:unknown):string{
  if(Array.isArray(value))return value.map(String).join(' > ');
  return value==null?'':String(value);
}

function isValidationItem(value:unknown):value is ValidationItem{
  return !!value&&typeof value==='object'&&('msg' in value||'loc' in value||'type' in value);
}

export function formatError(value:unknown):string{
  if(typeof value==='string')return value||'An unexpected error occurred.';
  if(value==null)return 'An unexpected error occurred.';
  if(value instanceof Error)return formatError(value.message);
  if(Array.isArray(value)){
    if(!value.length)return 'An unexpected error occurred.';
    const validation=value.every(isValidationItem);
    const lines=value.map(item=>{
      if(isValidationItem(item)){
        const loc=location(item.loc),message=typeof item.msg==='string'?item.msg:formatError(item.msg);
        return `${loc?`${loc}: `:''}${message}`;
      }
      return formatError(item);
    });
    return `${validation?'Validation error:\n':''}${lines.map(line=>`- ${line}`).join('\n')}`;
  }
  if(typeof value==='object'){
    const record=value as Record<string,unknown>;
    if('detail' in record)return formatError(record.detail);
    if('message' in record)return formatError(record.message);
    if('error' in record)return formatError(record.error);
    try{return JSON.stringify(value,null,2)}catch{return 'An unexpected error occurred.'}
  }
  return String(value);
}
